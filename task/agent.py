import asyncio
import json
from typing import Any

from aidial_client import AsyncDial
from aidial_client.types.chat.legacy.chat_completion import CustomContent, ToolCall
from aidial_sdk.chat_completion import Message, Role, Choice, Request, Response

from task.prompts import SYSTEM_PROMPT
from task.tools.base import BaseTool
from task.tools.models import ToolCallParams
from task.utils.constants import TOOL_CALL_HISTORY_KEY
from task.utils.history import unpack_messages
from task.utils.stage import StageProcessor


class GeneralPurposeAgent:

    def __init__(
            self,
            endpoint: str,
            system_prompt: str,
            tools: list[BaseTool],
    ):
        self.endpoint = endpoint
        self.system_prompt = system_prompt
        self.tools = tools
        self._tools_dict = {
            tool.name: tool
            for tool in tools
        }
        self.state = {
            TOOL_CALL_HISTORY_KEY: [],
        }

    async def handle_request(self, deployment_name: str, choice: Choice, request: Request, response: Response) -> Message:
        api_key = request.api_key
        async_dial = AsyncDial(api_key=api_key, base_url=self.endpoint, api_version=request.api_version)

        chunks = await async_dial.chat.completions.create(
            messages=self._prepare_messages(request.messages),
            deployment_name=deployment_name,
            stream=True,
            tools=[tool.schema for tool in self.tools],
        )
        tool_calls = []
        content = ''
        async for chunk in chunks:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta.content:
                    choice.append_content(delta.content)
                    content += delta.content
                if delta.tool_calls:
                    tool_calls = self._collect_tool_calls(delta.tool_calls)

        ai_message = Message(role=Role.ASSISTANT, content=content, tool_calls=tool_calls, custom_content=CustomContent(attachments=[]))
        if ai_message.tool_calls:
            tasks = [self._process_tool_call(tool_call, choice, api_key, request.headers.get('x-conversation-id', '')) for tool_call in ai_message.tool_calls]
            results = await asyncio.gather(*tasks)
            self.state[TOOL_CALL_HISTORY_KEY].append(ai_message.model_dump())
            self.state[TOOL_CALL_HISTORY_KEY].extend(results)
            return await self.handle_request(deployment_name=deployment_name, choice=choice, request=request, response=response)

        choice.set_state(state=self.state)
        return ai_message

    def _prepare_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        unpacked = unpack_messages(messages, state_history=self.state[TOOL_CALL_HISTORY_KEY])
        unpacked.insert(0, {
                "role": Role.SYSTEM.value,
                "content": self.system_prompt,
            })

        for msg in unpacked:
            print(f"Message: {json.dumps(msg)}")

        print('==================')
        return unpacked

    def _collect_tool_calls(self, tool_deltas):
        """Convert streaming tool call deltas to complete tool calls"""
        tool_dict = {}

        for delta in tool_deltas:
            idx = delta.index
            if delta.id: tool_dict[idx]["id"] = delta.id
            if delta.function.name: tool_dict[idx]["function"]["name"] = delta.function.name
            if delta.function.arguments: tool_dict[idx]["function"]["arguments"] += delta.function.arguments
            if delta.type: tool_dict[idx]["type"] = delta.type

        collected_tools = [ToolCall.validate(**tool_call) for tool_call in list(tool_dict.values())]
        return collected_tools

    async def _process_tool_call(self, tool_call: ToolCall, choice: Choice, api_key: str, conversation_id: str) -> dict[str, Any]:
        tool_name = tool_call.function.name
        stage = StageProcessor.open_stage(choice, tool_name)

        tool: BaseTool = self._tools_dict[tool_name]
        if tool.show_in_stage:
            stage.append_content("## Request arguments: \n")
            stage.append_content(f"```json\n\r{json.dumps(json.loads(tool_call.function.arguments), indent=2)}\n\r```\n\r")
            stage.append_content("## Response: \n")

        params = ToolCallParams(stage=stage, tool_call=tool_call, choice=choice, api_key=api_key, conversation_id=conversation_id)
        result = await tool.execute(params)

        StageProcessor.close_stage_safely(stage)
        return result.model_dump(exclude_none=True)
