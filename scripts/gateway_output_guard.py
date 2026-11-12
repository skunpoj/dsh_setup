"""Keep output aliases bounded; final-wire budgeting lives in the loopback proxy."""
from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from stream_admission_errors import install

install()


class OutputGuard(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if not isinstance(data, dict):
            return data
        physical_aliases = ('claude-3-5-sonnet-20241022', 'claude-3-7-sonnet-20250219', 'claude-opus-4-6', 'claude-sonnet-4', 'claude-sonnet-4-6', 'claude-sonnet-5', 'deepseek-chat', 'deepseek-flash', 'deepseek-reasoner', 'deepseek-v4', 'deepseek-v4-flash', 'deepseek-v4.1', 'deepseek-v4.1-flash', 'default', 'glm-5.3-flash', 'glm-flash', 'glm53flash', 'qwen3.8-27b', 'qwen3.8-flash-next')
        if str(data.get('model', '')).removeprefix('openai/') in physical_aliases and any(data.get(k) is not None for k in ['api_base', 'base_url', 'custom_llm_provider']):
            raise HTTPException(400, 'Managed context route does not accept endpoint/provider overrides.')
        if str(data.get('model', '')).removeprefix('openai/') not in {'deepseek-v4.1-flash', 'deepseek-flash'}:
            from custom_callbacks import proxy_handler_instance
            return await proxy_handler_instance.async_pre_call_hook(user_api_key_dict, cache, data, call_type)
        if any(data.get(k) is not None for k in ['api_base', 'base_url', 'custom_llm_provider']):
            raise HTTPException(400, 'Managed context route does not accept endpoint/provider overrides.')
        if not isinstance(data.get('messages'), list) or not data['messages']:
            raise HTTPException(400, 'This model route requires Chat Completions messages.')
        # This route is a plain OpenAI-compatible backend (DeepInfer serving deepseek-v4.1-flash),
        # not Anthropic. A client calling via the Anthropic Messages bridge (use_chat_completions_
        # url_for_anthropic_messages) may still send Anthropic's own 'safeguards' field (Claude
        # Code's auto-mode permission classifier); the bridge does not strip it the way litellm's
        # native /v1/messages adapter route does for non-Anthropic backends, so it reaches
        # AsyncCompletions.create(**kwargs) as an unsupported kwarg and 500s, which Claude Code
        # retries (observed live 2026-11-10, LANE6-SAFEGUARDS-TRACE). Refuse with a clean 4xx
        # instead of stripping: the same reason unattended_model_guard.py already uses for the
        # unattended-task path -- stripping would silently drop a safety capability the client
        # believes was applied, and a 4xx (unlike a 500) is not retried, so the retry loop ends
        # and the client can negotiate a supported shape.
        if 'safeguards' in data:
            raise HTTPException(400, 'unsupported-provider-safeguards')
        # Same bridge leak, different field: Anthropic's Messages API calls this
        # 'stop_sequences'; this plain OpenAI-compatible backend only knows 'stop'.
        # Unlike 'safeguards' there IS a direct equivalent here, so translate rather
        # than refuse -- rejecting would drop real, satisfiable stopping behavior for
        # no reason. Observed live 2026-11-10, same TypeError shape as the safeguards
        # case (LANE6-SAFEGUARDS-TRACE).
        if 'stop_sequences' in data:
            if 'stop' in data:
                raise HTTPException(400, 'Send stop or stop_sequences, not both.')
            data['stop'] = data.pop('stop_sequences')
        # This backend's streamed tool_use blocks are merged somewhere in the
        # translation path when the model emits more than one tool call in a
        # single turn: two tool-argument objects land concatenated inside one
        # tool_use's input ({"command": ...}{"file_path": ...}), which is not
        # valid JSON and makes the caller reject the whole call (observed live
        # 2026-11-10/11, lane 9 retained export, LANE6-PARALLEL-TOOLCALL-MERGE).
        # Forcing one tool call per turn avoids the merge outright; it costs an
        # extra round trip per additional tool the model would have batched.
        if data.get('tools'):
            data['parallel_tool_calls'] = False
        limits = [data[k] for k in ['max_tokens', 'max_completion_tokens'] if k in data]
        if any(type(n) is not int or n < 1 for n in limits):
            raise HTTPException(400, 'Output limits must be positive integers.')
        data.pop('max_completion_tokens', None)
        data['max_tokens'] = min([8192]+limits)
        return data


proxy_handler_instance = OutputGuard()
