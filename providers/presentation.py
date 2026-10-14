"""Normalize known transport-only user envelopes; preserve ordinary messages/code."""
import json
import re

QUESTION_REPLY = re.compile(r'\s*<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>\s*', re.S)


def clean_user_text(text):
    match=QUESTION_REPLY.fullmatch(text)
    if not match:
        return text
    fallback='Reply received; its contents could not be read.'
    try:
        replies=json.loads(match.group(1))
    except (ValueError,TypeError):
        return fallback
    if not isinstance(replies,list) or not 1<=len(replies)<=50:
        return fallback
    result=[]
    for item in replies:
        if not isinstance(item,dict):return fallback
        question,answer=item.get('question'),item.get('answer')
        if isinstance(answer,list) and all(isinstance(v,str) for v in answer):
            answer='; '.join(answer)
        if not isinstance(question,str) or not isinstance(answer,str):return fallback
        # Escape Markdown syntax in values: metadata must not turn into hidden images/links.
        literal=lambda value:re.sub(r'([\\`*_{}\[\]<>()#+.!|>-])',r'\\\1',value.strip())
        result.append('**Question**\n\n'+literal(question)+'\n\n**Answer**\n\n'+(literal(answer) or 'No answer provided.'))
    return '\n\n---\n\n'.join(result)
