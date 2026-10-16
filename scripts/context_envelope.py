"""Make prompt-affecting SGLang defaults explicit on both code paths."""


def normalize_conditioning(data):
    data.setdefault('continue_final_message', False)
    for tool in data.get('tools') or []:
        if isinstance(tool, dict) and tool.get('type') == 'function':
            function = tool.get('function')
            if isinstance(function, dict) and function.get('strict') is None:
                # The pinned TokenizeRequest converter materializes this
                # default. Forward it too so actual prompt IDs are identical.
                function['strict'] = False
    return data
