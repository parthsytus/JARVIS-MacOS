from core.lazy_loaders import call_complex_model
from core.jarvis_core import JARVIS_TOOLS, execute_tool_call

messages = [
    {'role': 'system', 'content': """You are JARVIS's Deep Research Agent. You have access to web search and file operations.

Your task: Research the user's query thoroughly, then create a well-structured report file.

Process:
1. Break down the query into searchable sub-questions
2. Search multiple sources for each aspect (use web_search multiple times with different queries)
3. Analyze and synthesize findings
4. Create a structured report with:
   - Executive Summary
   - Key Findings (with sources)
   - Pros/Cons comparison (if applicable)
   - Detailed Analysis
   - Recommendations
5. Save the FINAL REPORT using file_operation tool with: action: "create", folder: "desktop", content: [your complete report text]

CRITICAL RULES:
- After getting search results, READ them and EXTRACT key information
- Do NOT repeat the same search query
- When you have enough information, generate the FULL REPORT and SAVE IT using file_operation
- The file_operation tool requires: action="create", folder="desktop", content="[your complete report]"
- Do NOT say "see conversation above" - you must write the actual report content

Tools available: web_search, file_operation

Be thorough but efficient. The report should be genuinely useful, not a shallow dump."""},
    {'role': 'user', 'content': 'What is the latest iPhone model?'}
]

# Multi-turn test
for i in range(5):
    print(f'=== Turn {i+1} ===')
    response, error = call_complex_model(messages, tools=JARVIS_TOOLS, stream=False)
    
    if error:
        print(f'Error: {error}')
        break
    
    data = response.json()
    msg = data.get('message', {})
    content = msg.get('content', '')
    tool_calls = msg.get('tool_calls', [])
    
    print(f'Content: {content}')
    print(f'Tool calls: {tool_calls}')
    
    if content:
        messages.append({'role': 'assistant', 'content': content})
    
    if not tool_calls:
        print('No tool calls, stopping')
        break
    
    # Execute tool calls
    for tc in tool_calls:
        func_name = tc['function']['name']
        func_args = tc['function'].get('arguments', {})
        print(f'Executing: {func_name}({func_args})')
        result, needs_followup = execute_tool_call(func_name, func_args)
        messages.append({'role': 'tool', 'content': f'[{func_name}] {result}', 'name': func_name})
        print(f'Result: {result[:300]}...')