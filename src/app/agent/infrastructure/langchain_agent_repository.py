from .agent_repository_interface import IAgentRepository
from langchain_community.llms import Ollama
from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate
from langchain.tools import Tool
from langchain.memory import ConversationBufferWindowMemory

class LangchainAgentRepository(IAgentRepository):
    """Repository for interacting with a Langchain agent."""

    def __init__(self, agent_llm_config: dict, tools: list[Tool]):
        self.agent_llm_config = agent_llm_config
        self.tools = tools
        # Initialize memory for conversation context
        self.memory = ConversationBufferWindowMemory(
            k=5,  # Keep last 5 interactions
            return_messages=True,
            memory_key="chat_history"
        )
        self.agent_executor = self._initialize_agent()

    def _initialize_agent(self) -> AgentExecutor:
        """Initializes the Langchain agent."""
        llm = Ollama(
            base_url=self.agent_llm_config.get("ollama_endpoint"),
            model=self.agent_llm_config.get("model_name")
        )

        # Get the system prompt from config
        system_prompt = self.agent_llm_config.get("system_prompt", "")
        
        # Enhanced prompt template with conversation history
        prompt_template = f"""{system_prompt}

Herramientas disponibles: {{tools}}

Historial de conversación:
{{chat_history}}

INSTRUCCIONES:
- Mantén el contexto de la conversación anterior
- Para preguntas generales: responde directamente con "Final Answer: [tu respuesta]"
- Para consultar reportes/historial: usa la herramienta primero, luego responde
- Si el usuario hace referencia a algo mencionado antes, úsalo en tu respuesta

Formato cuando uses herramientas:
Thought: [por qué necesito esta herramienta]
Action: {{tool_names}}
Action Input: [parámetros]
Observation: [resultado]
Final Answer: [respuesta final]

{{input}}
{{agent_scratchpad}}"""

        prompt = PromptTemplate.from_template(prompt_template)

        # Create the ReAct agent
        agent = create_react_agent(llm=llm, tools=self.tools, prompt=prompt)

        # Create an agent executor with memory
        agent_executor = AgentExecutor(
            agent=agent, 
            tools=self.tools,
            memory=self.memory,
            verbose=False,
            handle_parsing_errors=True,
            max_iterations=8  # Increased for Llama3.2
        )

        print("Langchain ReAct Agent with memory initialized successfully.")
        return agent_executor

    async def send_message(self, user_message: str) -> str:
        """Sends a message to the Langchain agent and returns its response."""
        if self.agent_executor:
            try:
                response = await self.agent_executor.ainvoke({"input": user_message})
                return response.get("output", "No output from agent.")
            except Exception as e:
                print(f"Error during agent execution: {e}")
                return "Error: Could not get a response from the agent."
        return "Agent not initialized."
        
    def clear_memory(self):
        """Clears the conversation memory."""
        self.memory.clear()
        print("Conversation memory cleared.") 