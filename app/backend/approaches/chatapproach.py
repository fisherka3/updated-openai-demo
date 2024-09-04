import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional, Union

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
)

from approaches.approach import Approach
from core.messagebuilder import MessageBuilder
from azure.cosmos.aio import CosmosClient
from azure.cosmos import exceptions
import uuid
from datetime import datetime
import os

AZURE_COSMOSDB_ACCOUNT="db-temp-testingauth"
AZURE_COSMOSDB_DATABASE="db_conversation_history"
AZURE_COSMOSDB_CONVERSATIONS_CONTAINER="conversations"
AZURE_COSMOSDB_ACCOUNT_KEY = os.getenv("AZURE_COSMOSDB_ACCOUNT_KEY")

try:
    cosmos_endpoint = f'https://{AZURE_COSMOSDB_ACCOUNT}.documents.azure.com:443/'
    credential = AZURE_COSMOSDB_ACCOUNT_KEY
    database_name=AZURE_COSMOSDB_DATABASE
    container_name=AZURE_COSMOSDB_CONVERSATIONS_CONTAINER
        
except Exception as e:
    raise ValueError("Exception in CosmosDB initialization", e)
    cosmos_endpoint = None
    raise e

try:
    cosmosdb_client = CosmosClient(cosmos_endpoint, credential=credential)
except exceptions.CosmosHttpResponseError as e:
    if e.status_code == 401:
        raise ValueError("Invalid credentials") from e
    else:
        raise ValueError("Invalid CosmosDB endpoint") from e

try:
    database_client = cosmosdb_client.get_database_client(database_name)
except exceptions.CosmosResourceNotFoundError:
    raise ValueError("Invalid CosmosDB database name") 
 

try:
    container_client = database_client.get_container_client(container_name)
except exceptions.CosmosResourceNotFoundError:
    raise ValueError("Invalid CosmosDB container name") 

class ChatApproach(Approach, ABC):
    # Chat roles
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

    query_prompt_few_shots = [
        {"role": USER, "content": "How do I find which OnBase documents have deficiencies?"},
        {"role": ASSISTANT, "content": "OnBase documents deficiencies"},
        {"role": USER, "content": "How do I document home visits with the Remote Client?"},
        {"role": ASSISTANT, "content": "document home visits remote client"},
        {"role": USER, "content": "How do I enter orders for continuous tube feeding?"},
        {"role": ASSISTANT, "content": "order continous tube feeding"},
    ]
    NO_RESPONSE = "0"

    follow_up_questions_prompt_content = """Generate 3 very brief follow-up questions that the user would likely ask next.
    Enclose the follow-up questions in double angle brackets. Example:
    <<Are there exclusions for prescriptions?>>
    <<Which pharmacies can be ordered from?>>
    <<What is the limit for over-the-counter medication?>>
    Do no repeat questions that have already been asked.
    Make sure the last question ends with ">>".
    """

    query_prompt_template = "You are an assistant who generates terms based on a user question to be used as a search query in a very simple search engine. " +\
    "Below is a history of the conversation so far followed by a new question asked by the user. " +\
    "Your job is to generate terms for a search query based the user's question. " +\
    "Do not include any special characters. " +\
    "If the question is not in English, translate the question to English before generating the search query. " +\
    "If you cannot generate a search query, return just the number 0. "
    

    @property
    @abstractmethod
    def system_message_chat_conversation(self) -> str:
        pass

    @abstractmethod
    async def run_until_final_call(self, history, overrides, auth_claims, should_stream) -> tuple:
        pass

    def get_system_prompt(self, override_prompt: Optional[str], follow_up_questions_prompt: str) -> str:
        if override_prompt is None:
            return self.system_message_chat_conversation.format(
                injected_prompt="", follow_up_questions_prompt=follow_up_questions_prompt
            )
        elif override_prompt.startswith(">>>"):
            return self.system_message_chat_conversation.format(
                injected_prompt=override_prompt[3:] + "\n", follow_up_questions_prompt=follow_up_questions_prompt
            )
        else:
            return override_prompt.format(follow_up_questions_prompt=follow_up_questions_prompt)

    def get_search_query(self, chat_completion: ChatCompletion, user_query: str):
        response_message = chat_completion.choices[0].message
        if function_call := response_message.function_call:
            if function_call.name == "search_sources":
                arg = json.loads(function_call.arguments)
                search_query = arg.get("search_query", self.NO_RESPONSE)
                if search_query != self.NO_RESPONSE:
                    return search_query
        elif query_text := response_message.content:
            if query_text.strip() != self.NO_RESPONSE:
                return query_text
        return user_query

    def extract_followup_questions(self, content: str):
        return content.split("<<")[0], re.findall(r"<<([^>>]+)>>", content)

    def get_messages_from_history(
        self,
        system_prompt: str,
        model_id: str,
        history: list[dict[str, str]],
        user_content: Union[str, list[ChatCompletionContentPartParam]],
        max_tokens: int,
        few_shots=[],
    ) -> list[ChatCompletionMessageParam]:
        message_builder = MessageBuilder(system_prompt, model_id)

        # Add examples to show the chat what responses we want. It will try to mimic any responses and make sure they match the rules laid out in the system message.
        for shot in reversed(few_shots):
            message_builder.insert_message(shot.get("role"), shot.get("content"))

        append_index = len(few_shots) + 1

        message_builder.insert_message(self.USER, user_content, index=append_index)
        total_token_count = message_builder.count_tokens_for_message(dict(message_builder.messages[-1]))  # type: ignore

        newest_to_oldest = list(reversed(history[:-1]))
        for message in newest_to_oldest:
            potential_message_count = message_builder.count_tokens_for_message(message)
            if (total_token_count + potential_message_count) > max_tokens:
                logging.debug("Reached max tokens of %d, history will be truncated", max_tokens)
                break
            message_builder.insert_message(message["role"], message["content"], index=append_index)
            total_token_count += potential_message_count
        return message_builder.messages

    async def run_without_streaming(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        session_state: Any = None,
    ) -> dict[str, Any]:
        extra_info, chat_coroutine = await self.run_until_final_call(
            history, overrides, auth_claims, should_stream=False
        )
        chat_completion_response: ChatCompletion = await chat_coroutine
        chat_resp = chat_completion_response.model_dump()  # Convert to dict to make it JSON serializable
        chat_resp["choices"][0]["context"] = extra_info
        if overrides.get("suggest_followup_questions"):
            content, followup_questions = self.extract_followup_questions(chat_resp["choices"][0]["message"]["content"])
            chat_resp["choices"][0]["message"]["content"] = content
            chat_resp["choices"][0]["context"]["followup_questions"] = followup_questions
        chat_resp["choices"][0]["session_state"] = session_state

        conversation = {
            'id': str(uuid.uuid4()),
            'createdAt': datetime.utcnow().isoformat(),  
            'role': 'assistant',
            'content': str(chat_resp["choices"][0]["message"]["content"])
        }

        try:
            await container_client.upsert_item(conversation) 
        except exceptions.CosmosHttpResponseError as e:
            print(f"Error in create_convos upserting response: {e}")

        return chat_resp

    async def run_with_streaming(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        session_state: Any = None,
    ) -> AsyncGenerator[dict, None]:
        extra_info, chat_coroutine = await self.run_until_final_call(
            history, overrides, auth_claims, should_stream=True
        )
        yield {
            "choices": [
                {
                    "delta": {"role": self.ASSISTANT},
                    "context": extra_info,
                    "session_state": session_state,
                    "finish_reason": None,
                    "index": 0,
                }
            ],
            "object": "chat.completion.chunk",
        }

        followup_questions_started = False
        followup_content = ""
        async for event_chunk in await chat_coroutine:
            # "2023-07-01-preview" API version has a bug where first response has empty choices
            event = event_chunk.model_dump()  # Convert pydantic model to dict
            if event["choices"]:
                # if event contains << and not >>, it is start of follow-up question, truncate
                content = event["choices"][0]["delta"].get("content")
                content = content or ""  # content may either not exist in delta, or explicitly be None
                if overrides.get("suggest_followup_questions") and "<<" in content:
                    followup_questions_started = True
                    earlier_content = content[: content.index("<<")]
                    if earlier_content:
                        event["choices"][0]["delta"]["content"] = earlier_content
                        yield event
                    followup_content += content[content.index("<<") :]
                elif followup_questions_started:
                    followup_content += content
                else:
                    yield event
        if followup_content:
            _, followup_questions = self.extract_followup_questions(followup_content)
            yield {
                "choices": [
                    {
                        "delta": {"role": self.ASSISTANT},
                        "context": {"followup_questions": followup_questions},
                        "finish_reason": None,
                        "index": 0,
                    }
                ],
                "object": "chat.completion.chunk",
            }

    async def run(
        self, messages: list[dict], stream: bool = False, session_state: Any = None, context: dict[str, Any] = {}
    ) -> Union[dict[str, Any], AsyncGenerator[dict[str, Any], None]]:
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})

        if stream is False:
            return await self.run_without_streaming(messages, overrides, auth_claims, session_state)
        else:
            return self.run_with_streaming(messages, overrides, auth_claims, session_state)
