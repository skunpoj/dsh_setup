import litellm
from litellm.integrations.custom_logger import CustomLogger

MAX_CONTEXT_TOKENS = 131072
MAX_OUTPUT_TOKENS = 8192
SAFETY_BUFFER_TOKENS = 256


class DynamicContextClamper(CustomLogger):
    """Clamp legacy and current requests to the deployed model limits."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if not data or not isinstance(data, dict):
            return data

        messages = data.get("messages")
        if not messages or not isinstance(messages, list):
            return data

        try:
            input_tokens = litellm.token_counter(
                model="deepseek-flash", messages=messages
            )
        except Exception:
            total_chars = sum(
                len(str(message.get("content", "")))
                for message in messages
                if isinstance(message, dict)
            )
            input_tokens = int(total_chars / 3.0) + len(messages) * 4

        available_output = (
            MAX_CONTEXT_TOKENS - input_tokens - SAFETY_BUFFER_TOKENS
        )
        if available_output < 1:
            raise ValueError(
                "Input exceeds the verified 128K context budget; compact the session "
                "or start a new session before retrying."
            )

        requested_output = data.get("max_tokens")
        if not isinstance(requested_output, int) or requested_output < 1:
            requested_output = MAX_OUTPUT_TOKENS

        data["max_tokens"] = min(
            requested_output,
            MAX_OUTPUT_TOKENS,
            available_output,
        )
        return data


proxy_handler_instance = DynamicContextClamper()
