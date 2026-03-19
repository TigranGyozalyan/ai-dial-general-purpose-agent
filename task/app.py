import os

import uvicorn
from aidial_sdk import DIALApp
from aidial_sdk.chat_completion import ChatCompletion, Request, Response

from task.agent import GeneralPurposeAgent
from task.prompts import SYSTEM_PROMPT
from task.tools.base import BaseTool
from task.tools.deployment.image_generation_tool import ImageGenerationTool
from task.tools.files.file_content_extraction_tool import FileContentExtractionTool
from task.tools.py_interpreter.python_code_interpreter_tool import PythonCodeInterpreterTool
from task.tools.mcp.mcp_client import MCPClient
from task.tools.mcp.mcp_tool import MCPTool
from task.tools.rag.document_cache import DocumentCache
from task.tools.rag.rag_tool import RagTool

DIAL_ENDPOINT = os.getenv('DIAL_ENDPOINT', "http://localhost:8080")
# DEPLOYMENT_NAME = os.getenv('DEPLOYMENT_NAME', 'gpt-4o')
DEPLOYMENT_NAME = os.getenv('DEPLOYMENT_NAME', 'claude-haiku-4-5')


class GeneralPurposeAgentApplication(ChatCompletion):

    def __init__(self):
        self.tools: list[BaseTool] = []

    async def _get_mcp_tools(self, url: str) -> list[BaseTool]:
        tools = []
        mcp_client = MCPClient(url)

        for tool in await mcp_client.get_tools():
            tools.append(MCPTool(client=mcp_client, mcp_tool_model=tool))
        return tools

    async def _create_tools(self) -> list[BaseTool]:
        python_mcp_url = 'http://localhost:8050/mcp'
        interpreter = await PythonCodeInterpreterTool.create(
                mcp_url=python_mcp_url,
                tool_name="execute_code",
                dial_endpoint=DIAL_ENDPOINT
            )
        tools: list[BaseTool] = [
            RagTool(endpoint=DIAL_ENDPOINT, deployment_name=DEPLOYMENT_NAME, document_cache=DocumentCache.create()),
            FileContentExtractionTool(endpoint=DIAL_ENDPOINT),
            ImageGenerationTool(endpoint=DIAL_ENDPOINT),
            interpreter
        ]
        mcp_tools = await self._get_mcp_tools('http://localhost:8051/mcp')
        tools.extend(mcp_tools)
        return tools

    async def chat_completion(self, request: Request, response: Response) -> None:
        if not self.tools:
            self.tools = await self._create_tools()

        with response.create_single_choice() as choice:
            agent = GeneralPurposeAgent(endpoint=DIAL_ENDPOINT, system_prompt = SYSTEM_PROMPT, tools=self.tools)
            await agent.handle_request(choice=choice, deployment_name=DEPLOYMENT_NAME, request=request, response=response)

app = DIALApp()
agent_app = GeneralPurposeAgentApplication()
app.add_chat_completion(deployment_name="general-purpose-agent", impl=agent_app)

uvicorn.run(app, port=5030, host="0.0.0.0")