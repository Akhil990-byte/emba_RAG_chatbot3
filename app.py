import streamlit as st
import json
import os
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_pinecone import PineconeVectorStore
from flashrank import Ranker, RerankRequest

# ==============================================================================
# 1. PAGE AND BACKEND CONFIGURATION
# ==============================================================================

# --- Use the full page width for a more spacious layout
st.set_page_config(page_title="Eller EMBA AI Assistant", layout="wide", page_icon="📘")

# --- Load API Keys and Configuration from Streamlit Secrets ---
# In your Streamlit Cloud account, set these in "Settings" -> "Secrets"
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    pinecone_api_key = st.secrets["PINECONE_API_KEY"]
    # It's best practice to store the index name in secrets as well
    index_name = st.secrets.get("PINECONE_INDEX_NAME", "eller-executive-edu-ak-final")
except KeyError as e:
    st.error(f"🚨 Missing Secret: Please set {e} in your Streamlit Cloud app settings.", icon="🚨")
    st.stop()

# --- Initialize Backend Components (using Streamlit's caching) ---
# @st.cache_resource ensures these heavy objects are loaded only ONCE per session.
@st.cache_resource
def initialize_backend_components():
    """
    Initializes all the necessary backend components for the RAG pipeline.
    This function is cached to prevent reloading on every interaction.
    """
    print("Initializing backend components for the first time...")
    
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=openai_api_key)
    vector_store = PineconeVectorStore(index_name=index_name, embedding=embeddings)
    llm = ChatOpenAI(model="gpt-4-turbo", temperature=0.5, openai_api_key=openai_api_key, seed=12039)
    ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank_cache")
    output_parser = StrOutputParser()
    
    print("Components initialized successfully.")
    return vector_store, llm, ranker, output_parser

vector_store, llm, ranker, output_parser = initialize_backend_components()

# --- Define Helper Functions and Chains ---
def rerank_docs(query, docs):
    """Re-ranks documents using FlashRank for higher relevance."""
    passages = [doc.page_content for doc in docs]
    rerank_request = RerankRequest(query=query, passages=passages)
    reranked_results = ranker.rerank(rerank_request)
    return [result['text'] for result in reranked_results[:5]]

# The main prompt template and generation chain
qa_template = """
You are an expert AI assistant for Eller Executive Education. Your tone is professional, insightful, and academic.
Based ONLY on the provided context, synthesize a comprehensive answer to the user's question.
If the information is not in the context, state clearly: "Based on the provided documents, I cannot find information on that topic."

After providing the answer, suggest 2-3 relevant follow-up questions under a "--- \n*Suggested Follow-ups:*" heading.

Context:
{context}

User Question:
{question}

Formatted Response:
"""
qa_prompt = PromptTemplate.from_template(qa_template)
generate_answer_chain = qa_prompt | llm | output_parser

# ==============================================================================
# 2. USER INTERFACE
# ==============================================================================

st.title("📘 Eller Executive Education AI Assistant")
st.caption("Your intelligent partner for exploring course materials.")

# --- Sidebar for Topic Filtering ("Smart Section Labeling") ---
with st.sidebar:
    st.header("Search Controls")
    st.markdown("Select a topic to focus the AI's search.")
    
    # Load topics from the topics.json file
    try:
        with open("topics.json", "r") as f:
            available_filters = json.load(f)
    except FileNotFoundError:
        st.error("`topics.json` not found. Please ensure it's in your GitHub repository.")
        available_filters = ["All"]

    selected_filter = st.selectbox(
        label="Refine Search by Document or Topic",
        options=available_filters
    )

# --- Main Chat Interface Logic ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_prompt := st.chat_input("Ask a question about your course materials..."):
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # --- RAG Execution Logic ---
            search_kwargs = {"k": 25}
            if selected_filter != "All":
                search_kwargs['filter'] = {"topics": {"$in": [selected_filter]}}
            
            retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
            initial_docs = retriever.get_relevant_documents(user_prompt)
            
            if not initial_docs:
                response = "I could not find relevant information for that specific topic. Please try another search or select 'All' from the dropdown."
            else:
                reranked_context = "\n\n---\n\n".join(rerank_docs(user_prompt, initial_docs))
                response = generate_answer_chain.invoke({
                    "question": user_prompt,
                    "context": reranked_context
                })
            
            st.markdown(response)
    
    st.session_state.messages.append({"role": "assistant", "content": response})
