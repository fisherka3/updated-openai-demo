from typing import Any, Coroutine, Literal, Optional, Union, overload

from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorQuery
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
)

from approaches.approach import ThoughtStep
from approaches.chatapproach import ChatApproach
from core.authentication import AuthenticationHelper
from core.modelhelper import get_token_limit

import re
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


class ChatReadRetrieveReadApproach(ChatApproach):

    """
    A multi-step approach that first uses OpenAI to turn the user's question into a search query,
    then uses Azure AI Search to retrieve relevant documents, and then sends the conversation history,
    original user question, and search results to OpenAI to generate a response.
    """

    def __init__(
        self,
        *,
        search_client: SearchClient,
        auth_helper: AuthenticationHelper,
        openai_client: AsyncOpenAI,
        chatgpt_model: str,
        chatgpt_deployment: Optional[str],  # Not needed for non-Azure OpenAI
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_model: str,
        sourcepage_field: str,
        content_field: str,
        query_language: str,
        query_speller: str,
    ):
        self.search_client = search_client
        self.openai_client = openai_client
        self.auth_helper = auth_helper
        self.chatgpt_model = chatgpt_model
        self.chatgpt_deployment = chatgpt_deployment
        self.embedding_deployment = embedding_deployment
        self.embedding_model = embedding_model
        self.sourcepage_field = sourcepage_field
        self.content_field = content_field
        self.query_language = query_language
        self.query_speller = query_speller
        self.chatgpt_token_limit = get_token_limit(chatgpt_model)

    @property
    def system_message_chat_conversation(self):
        prompt = "You are an assistant helping users of Epic software answer questions and find information. " +\
        "Above is a history of the conversation so far. " +\
        """The user will provide a question along with a list of sources and information from the sources. 
        Each source has a name followed by a newline and then then actual information. For example: 
        user question 
        Sources: info1.pdf#page=3 \n information from info1.pdf#page=3, \n
        info2.pdf#page=6 \n information from info2.pdf#page=6, \n
        info3.pdf#page=2 \n information from info3.pdf#page=2 \n
        """ +\
        "Answer ONLY with the facts listed in the list of sources below. " +\
        "Concisely answer ONLY the question asked by using ONLY the information from the sources provided by the user. " +\
        "Do not generate answers that don't use the sources below. " +\
        "If there isn't enough information provided in the sources, then say you don't know. " +\
        "If asking a clarifying question to the user would help, then ask the question. " +\
        "Do not fomat your response with markdown, use plain text. " +\
        "Always include the source name for each fact you use in the response. " +\
        "Use square brackets to reference the source, for example [info1.pdf#page=3]. " +\
        """Do not combine sources, you must list each source referenced separately, for example: [info1.pdf#page=3][info2.pdf#page=6][info3.pdf#page=2]. " +\
        "Other than adding brackets, do not alter the source, use the file or link provided as is."
        {follow_up_questions_prompt}
        {injected_prompt}
        """
        return prompt

    @overload
    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: Literal[False],
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, ChatCompletion]]:
        ...

    @overload
    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: Literal[True],
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, AsyncStream[ChatCompletionChunk]]]:
        ...

    async def run_until_final_call(
        self,
        history: list[dict[str, str]],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: bool = False,
    ) -> tuple[dict[str, Any], Coroutine[Any, Any, Union[ChatCompletion, AsyncStream[ChatCompletionChunk]]]]:
        has_text = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        has_vector = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        use_semantic_captions = True if overrides.get("semantic_captions") and has_text else False
        top = overrides.get("top", 3)
        filter = self.build_filter(overrides, auth_claims)
        use_semantic_ranker = True if overrides.get("semantic_ranker") and has_text else False

        original_user_query = history[-1]["content"]
        user_query_request = str(original_user_query)

        conversation = {
            'id': str(uuid.uuid4()),
            'createdAt': datetime.utcnow().isoformat(),  
            'role': 'user',
            'content': user_query_request
        }

        try:
            await container_client.upsert_item(conversation) 
        except exceptions.CosmosHttpResponseError as e:
            print(f"Error in create_convos upserting question: {e}")
    

        last_response = ""
        all_hx = []
        for line in history:
            if line['role']=='assistant':
                last_response = str(line['content'])
            if line['role']=='history':
                all_hx = line['content']

        if last_response: all_hx.append({'role': 'assistant2', 'content': last_response})
        all_hx.append({'role':'user1', 'content':user_query_request})
        history = [line for line in history if line['role'] != 'history']

        query_hx = []
        for line in all_hx:
            if line['role']=='user1':
                query_hx.append({'role':'user', 'content':line['content']})
            if line['role']=='assistant1':
                query_hx.append({'role':'assistant', 'content':line['content']})

        functions = [
            {
                "name": "search_sources",
                "description": "Retrieve sources from the Azure AI Search index",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search_query": {
                            "type": "string",
                            "description": "Query string to retrieve documents from azure search eg: 'Health care plan'",
                        }
                    },
                    "required": ["search_query"],
                },
            }
        ]

        # STEP 1: Generate an optimized keyword search query based on the chat history and the last question
        messages = self.get_messages_from_history(
            system_prompt=self.query_prompt_template,
            model_id=self.chatgpt_model,
            history=query_hx,
            user_content=user_query_request,
            max_tokens=self.chatgpt_token_limit - len(user_query_request),
            few_shots=self.query_prompt_few_shots,
        )

        search_query_msg = messages

        chat_completion: ChatCompletion = await self.openai_client.chat.completions.create(
            messages=messages,  # type: ignore
            # Azure Open AI takes the deployment name as the model name
            model=self.chatgpt_deployment if self.chatgpt_deployment else self.chatgpt_model,
            temperature=0.0,
            max_tokens=100,  # Setting too low risks malformed JSON, setting too high may affect performance
            n=1,
            functions=functions,
            function_call="auto",
        )

        query_text = self.get_search_query(chat_completion, original_user_query)

        # STEP 2: Retrieve relevant documents from the search index with the GPT optimized query

        # If retrieval mode includes vectors, compute an embedding for the query
        vectors: list[VectorQuery] = []
        if has_vector:
            vectors.append(await self.compute_text_embedding(query_text))

        # Only keep the text query if the retrieval mode uses text, otherwise drop it
        if not has_text:
            query_text = None

        all_hx.append({'role': 'assistant1', 'content': query_text})

        conversation = {
            'id': str(uuid.uuid4()),
            'createdAt': datetime.utcnow().isoformat(),  
            'role': 'query',
            'content': query_text
        }

        try:
            await container_client.upsert_item(conversation) 
        except exceptions.CosmosHttpResponseError as e:
            print(f"Error in create_convos upserting query: {e}")

        results = await self.search(top, query_text, filter, vectors, use_semantic_ranker, use_semantic_captions)

        sources_content = self.get_sources_content(results, use_semantic_captions, use_image_citation=False)
        content = ",\n".join(sources_content)
        all_hx.append({'role': 'user2', 'content': original_user_query + " \n\n Sources: \n" + content})

        conversation = {
            'id': str(uuid.uuid4()),
            'createdAt': datetime.utcnow().isoformat(),  
            'role': 'results',
            'content': content
        }

        try:
            await container_client.upsert_item(conversation) 
        except exceptions.CosmosHttpResponseError as e:
            print(f"Error in create_convos upserting results: {e}")

        # STEP 3: Generate a contextual and content specific answer using the search results and chat history

        # Allow client to replace the entire prompt, or to inject into the exiting prompt using >>>
        system_message = self.get_system_prompt(
            overrides.get("prompt_template"),
            self.follow_up_questions_prompt_content if overrides.get("suggest_followup_questions") else "",
        )

        response_token_limit = 4000
        messages_token_limit = self.chatgpt_token_limit - response_token_limit

        chat_hx = []
        for line in all_hx:
            if line['role']=='user2':
                chat_hx.append({'role':'user', 'content':line['content']})
            if line['role']=='assistant2':
                chat_hx.append({'role':'assistant', 'content':line['content']})

        chat_messages = self.get_messages_from_history(
            system_prompt=system_message,
            model_id=self.chatgpt_model,
            history=chat_hx,
            # Model does not handle lengthy system messages well. Moving sources to latest user conversation to solve follow up questions prompt.
            user_content=original_user_query + "\n Sources: \n" + content,
            max_tokens=messages_token_limit,
        )

        if len(chat_messages) > 4:
            chat_messages = [chat_messages[0]] + chat_messages[-3:]

        data_points = {"text": sources_content}

        chat_coroutine = self.openai_client.chat.completions.create(
            # Azure Open AI takes the deployment name as the model name
            model=self.chatgpt_deployment if self.chatgpt_deployment else self.chatgpt_model,
            messages=chat_messages,
            temperature=0.0,
            max_tokens=response_token_limit,
            n=1,
            stream=should_stream,
        )

        extra_info = {
            "history": all_hx,
            "data_points": data_points,
            "thoughts": [
                ThoughtStep(
                    "[CRR]: search prompt",
                    [str(s) for s in search_query_msg],
                ),
                ThoughtStep(
                    "Generated search query",
                    query_text,
                    {"use_semantic_captions": use_semantic_captions, "has_vector": has_vector, "include_category": filter},
                ),
                ThoughtStep(
                    "history:",
                    [str(h) for h in history],
                ),
                ThoughtStep(
                    "all history!",
                    [str(h) for h in all_hx],
                ),
                ThoughtStep("Results", [result.serialize_for_results() for result in results]),
                ThoughtStep("Prompt", [str(message) for message in chat_messages]),
            ],
        }

        return (extra_info, chat_coroutine)