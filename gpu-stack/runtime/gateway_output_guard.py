"""Keep output aliases bounded; final-wire budgeting lives in the loopback proxy."""
from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger


class OutputGuard(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if not isinstance(data, dict):
            return data
        if str(data.get('model', '')).removeprefix('openai/') not in {'deepseek-v4.1-flash', 'deepseek-flash'}:
            raise HTTPException(400, 'Only the configured local model aliases are supported.')
        if any(data.get(k) is not None for k in ['api_base', 'base_url', 'custom_llm_provider']):
            raise HTTPException(400, 'Managed context route does not accept endpoint/provider overrides.')
        if not isinstance(data.get('messages'), list) or not data['messages']:
            raise HTTPException(400, 'This model route requires Chat Completions messages.')
        limits = [data[k] for k in ['max_tokens', 'max_completion_tokens'] if k in data]
        if any(type(n) is not int or n < 1 for n in limits):
            raise HTTPException(400, 'Output limits must be positive integers.')
        data.pop('max_completion_tokens', None)
        data['max_tokens'] = min([8192]+limits)
        return data


proxy_handler_instance = OutputGuard()
