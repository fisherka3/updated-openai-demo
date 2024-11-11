import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator, List, Optional, Union, cast

import aiohttp
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import (
    CaptionResult,
    QueryType,
    RawVectorQuery,
    VectorQuery,
)
from openai import AsyncOpenAI

from core.authentication import AuthenticationHelper
from text import nonewlines


@dataclass
class Document:
    id: Optional[str]
    content: Optional[str]
    embedding: Optional[List[float]]
    image_embedding: Optional[List[float]]
    category: Optional[str]
    sourcepage: Optional[str]
    sourcefile: Optional[str]
    oids: Optional[List[str]]
    groups: Optional[List[str]]
    captions: List[CaptionResult]

    def serialize_for_results(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "embedding": Document.trim_embedding(self.embedding),
            "imageEmbedding": Document.trim_embedding(self.image_embedding),
            "category": self.category,
            "sourcepage": self.sourcepage,
            "sourcefile": self.sourcefile,
            "oids": self.oids,
            "groups": self.groups,
            "captions": [
                {
                    "additional_properties": caption.additional_properties,
                    "text": caption.text,
                    "highlights": caption.highlights,
                }
                for caption in self.captions
            ]
            if self.captions
            else [],
        }

    @classmethod
    def trim_embedding(cls, embedding: Optional[List[float]]) -> Optional[str]:
        """Returns a trimmed list of floats from the vector embedding."""
        if embedding:
            if len(embedding) > 2:
                # Format the embedding list to show the first 2 items followed by the count of the remaining items."""
                return f"[{embedding[0]}, {embedding[1]} ...+{len(embedding) - 2} more]"
            else:
                return str(embedding)

        return None


@dataclass
class ThoughtStep:
    title: str
    description: Optional[Any]
    props: Optional[dict[str, Any]] = None


class Approach:
    def __init__(
        self,
        search_client: SearchClient,
        openai_client: AsyncOpenAI,
        auth_helper: AuthenticationHelper,
        query_language: Optional[str],
        query_speller: Optional[str],
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_model: str,
        openai_host: str,
    ):
        self.search_client = search_client
        self.openai_client = openai_client
        self.auth_helper = auth_helper
        self.query_language = query_language
        self.query_speller = query_speller
        self.embedding_deployment = embedding_deployment
        self.embedding_model = embedding_model
        self.openai_host = openai_host

    def build_filter(self, overrides: dict[str, Any], auth_claims: dict[str, Any]) -> Optional[str]:

        others = ["Admission Staff",
            "Surgeon/Provider",
            "Payment Posting Staff",
            "Infection Preventionists",
            "ROI Staff",
            "OR Manager",
            "Central Scheduler",
            "IntraOp RN",
            "Radiologist",
            "Coders",
            "Credentialed Trainers",
            "Credit Analysts",
            "EpicCare Link",
            "Anesthesiologist",
            "Community Connect",
            "OR Scheduler",
            "Pre/Post RN",
            "Ambulatory Pharmacist",
            "Financial Counselors",
            "CRNA",
            "Nurse Triage",
            "PACU RN",
            "Self Pay Staff",
            "Deficiency Analyst",
            "Lab Staff",
            "Registration / Scheduling (Pre-registration, Virtual Registration, Auth/Cert or Front Desk)",
            "Auth/Cert",
            "Charge Poster",
            "PAT RN",
            "Bed Planners",
            "Transport Staff",
            "Advanced Care",
            "Interventional Technologist",
            "Nurse Liaison",
            "Research Billing Staff",
            "Clinic Surgery Coordinator",
            "Electronic Imaging Technicians (EIT)",
            "Interventional Scheduler",
            "PACE",
            "Pre/Post Tech",
            "SNRA",
            "Unit Clerk",
            "Audit/Compliance Staff",
            "Financial Coders",
            "PACU Tech",
            "Patient Placement Staff"
        ]

        include_category = overrides.get("include_category") or None
        include_version = overrides.get("include_version") or None
        include_audience = overrides.get("include_audience") or None
        security_filter = self.auth_helper.build_security_filters(overrides, auth_claims)
        filters = []

        if include_category:
            category_filter_expression = " and ".join([f"category ne '{item.strip()}'" for item in include_category.split(",")])
            filters.append(category_filter_expression)

        if include_version:
            if len(include_version.split(",")) < 14:
                version_filter_expression = " or ".join([f"version eq '{item.strip()}'" for item in include_version.split(",")])
                version_filter_expression += "or version eq 'None'"
                filters.append(version_filter_expression)

        if include_audience:
            if len(include_audience.split("|")) < 30:
                audience_list = [item.strip() for item in include_audience.split("|")]
                expanded_audience_list = [item if item != 'Other' else others for item in audience_list]
                flat_audience_list = [aud for sublist in expanded_audience_list for aud in (sublist if isinstance(sublist, list) else [sublist])]
                audience_filter_parts = [f"a eq '{item}'" for item in flat_audience_list]
                audience_filter_parts.append("a eq 'None'")
                audience_filter_parts.append("a eq 'All Staff'")
                filters.append(f"audience/any(a: {' or '.join(audience_filter_parts)})")

        if security_filter:
            filters.append(security_filter)

        return None if len(filters) == 0 else " and ".join(f"({item})" for item in filters)

    async def search(
        self,
        top: int,
        query_text: Optional[str],
        filter: Optional[str],
        vectors: List[VectorQuery],
        use_semantic_ranker: bool,
        use_semantic_captions: bool,
    ) -> List[Document]:
        # Use semantic ranker if requested and if retrieval mode is text or hybrid (vectors + text)
        if use_semantic_ranker and query_text:
            results = await self.search_client.search(
                search_text=query_text,
                scoring_statistics="global",
                filter=filter,
                query_type=QueryType.SEMANTIC,
                query_language=self.query_language,
                query_speller=self.query_speller,
                semantic_configuration_name="default",
                top=top,
                query_caption="extractive|highlight-false" if use_semantic_captions else None,
                vector_queries=vectors,
            )
        else:
            results = await self.search_client.search(
                search_text=query_text or "", filter=filter, top=top, vector_queries=vectors
            )

        documents = []
        async for page in results.by_page():
            async for document in page:
                documents.append(
                    Document(
                        id=document.get("id"),
                        content=document.get("content"),
                        embedding=document.get("embedding"),
                        image_embedding=document.get("imageEmbedding"),
                        category=document.get("category"),
                        sourcepage=document.get("sourcepage"),
                        sourcefile=document.get("sourcefile"),
                        oids=document.get("oids"),
                        groups=document.get("groups"),
                        captions=cast(List[CaptionResult], document.get("@search.captions")),
                    )
                )
        return documents

    def get_sources_content(
        self, results: List[Document], use_semantic_captions: bool, use_image_citation: bool
    ) -> list[str]:
        if use_semantic_captions:
            return [
                (self.get_citation((doc.sourcepage or ""), use_image_citation))
                + " \n "
                + nonewlines(" . ".join([cast(str, c.text) for c in (doc.captions or [])]))
                for doc in results
            ]
        else:
            return [
                (self.get_citation((doc.sourcepage or ""), use_image_citation)) + "  \n " + nonewlines(doc.content or "")
                for doc in results
            ]

    def get_citation(self, sourcepage: str, use_image_citation: bool) -> str:
        if use_image_citation:
            return sourcepage
        else:
            path, ext = os.path.splitext(sourcepage)
            if ext.lower() == ".png":
                page_idx = path.rfind("-")
                page_number = int(path[page_idx + 1 :])
                return f"{path[:page_idx]}.pdf#page={page_number}"

            return sourcepage

    async def compute_text_embedding(self, q: str):
        embedding = await self.openai_client.embeddings.create(
            # Azure Open AI takes the deployment name as the model name
            model=self.embedding_deployment if self.embedding_deployment else self.embedding_model,
            input=q,
        )
        query_vector = embedding.data[0].embedding
        return RawVectorQuery(vector=query_vector, k=50, fields="embedding")

    async def compute_image_embedding(self, q: str, vision_endpoint: str, vision_key: str):
        endpoint = f"{vision_endpoint}computervision/retrieval:vectorizeText"
        params = {"api-version": "2023-02-01-preview", "modelVersion": "latest"}
        headers = {"Content-Type": "application/json", "Ocp-Apim-Subscription-Key": vision_key}
        data = {"text": q}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=endpoint, params=params, headers=headers, json=data, raise_for_status=True
            ) as response:
                json = await response.json()
                image_query_vector = json["vector"]
        return RawVectorQuery(vector=image_query_vector, k=50, fields="imageEmbedding")

    async def run(
        self, messages: list[dict], stream: bool = False, session_state: Any = None, context: dict[str, Any] = {}
    ) -> Union[dict[str, Any], AsyncGenerator[dict[str, Any], None]]:
        raise NotImplementedError
