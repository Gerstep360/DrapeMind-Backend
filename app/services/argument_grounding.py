"""Conservative optional-filter validation, not an intent classifier."""
import re
import unicodedata


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold())
                   if not unicodedata.combining(c))


def unsupported_filters(schema, arguments, message, constraints):
    invalid = []
    for name, spec in schema.get('properties', {}).items():
        value = arguments.get(name)
        if value is None or value == {} or value == []:
            continue
        context_value = constraints.get(name)
        if context_value is not None and normalized(context_value) == normalized(value):
            continue
        if spec.get('x-context-only'):
            invalid.append(name)
        elif spec.get('x-user-grounded'):
            # Exact evidence only; paraphrases require clarification, never a guessed filter.
            values = value if isinstance(value, list) else [value]
            if any(not re.search(r'(?<!\w)' + re.escape(normalized(item)) + r'(?!\w)', normalized(message)) for item in values):
                invalid.append(name)
    return invalid
