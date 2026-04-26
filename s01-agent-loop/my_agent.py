from anthropic import Anthropic
from dotenv import load_dotenv                                   
import os                                                        
import subprocess                                                
                                                                
load_dotenv(override=True)                                       
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]                                   
                                                                
tools = [{                                                       
    "name": "bash",                                              
    "description": "执行bash命令",                               
    "input_schema": {                                            
        "type": "object",                                        
        "properties": {"command": {"type": "string"}},           
        "required": ["command"]                                  
    }                                                            
}]                                                               
                
query = input("你: ")                                            
messages = [{"role": "user", "content": query}]
                                                                
while True:                                                      
    # 1. 调 API                                                  
    response = client.messages.create(                           
        model=MODEL, 
        max_tokens=8000, 
        tools=tools,
        messages=messages                                                
    )           
                                                                
    # 2. 把 LLM 的回复追加到 messages                            
    messages.append({"role": "assistant", "content": response.content})                                               
                
    # 3. 检查退出条件                                            
    if response.stop_reason != "tool_use":
        # 打印最终回复，然后退出                                 
        for block in messages[-1]["content"]:                                                  
            if hasattr(block, "text"):                                                         
                print(block.text)    
        break                                         
                                                                
    # 4. 执行工具，构造 tool_result                              
    results = []                                                 
    for block in response.content:                               
        if block.type == "tool_use":
            # 执行命令，拿到输出                                 
            tool_result = subprocess.run(
               block.input["command"],
               shell=True,
               capture_output=True, 
               text=True 
            )  
            output = tool_result.stdout                                      
            results.append({                                     
                "type": "tool_result",                           
                "tool_use_id": block.id,                         
                "content": output                                
            })                                                   
                                                                
    # 5. 把工具结果追加到 messages，循环回去                     
    messages.append({"role": "user", "content": results})                                         
                                                                
print("结束") 

# Message(
#     id='94e7f532-a064-4a6a-9504-eb04496ccf41', 
#     content=[TextBlock(citations=None, 
#                         text='中国是一个位于东亚的社会主义国家，首都北京。它拥有悠久的历史和灿烂的文化，是世界上人口最多的国家之一，也是全球第二大经济体。中国以其快速的经济增长、丰富的文化遗产（如长城、故宫、兵马俑）、多样的自然景观（如黄山、桂林山水）以及现代城市的快速发展（如北京、上海、深圳）而闻名。中国的政治体制是中国共产党领导的多党合作和政治协商制度，国家元首是国家主席，政府首脑是国务院总理。近年来，中国在科技创新、基础设施建设（如高铁网络）、航天探索（如嫦娥探月工程）以及环境保护等方面取得了显著成就。同时，中国也积极参与全球治理，推动构建人类命运共同体。', 
#                         type='text')], 
#     model='deepseek-v4-flash', 
#     role='assistant', 
#     stop_reason='end_turn', 
#     stop_sequence=None, 
#     type='message', 
#     usage=Usage(cache_creation=None, 
#                 cache_creation_input_tokens=0, 
#                 cache_read_input_tokens=0, 
#                 input_tokens=6, 
#                 output_tokens=140, 
#                 server_tool_use=None, 
#                 service_tier='standard')
# )

# Message(
#     id='4d3378ae-d95c-4823-942f-a9174c5b1cd9', 
#     content=[ToolUseBlock(id='call_00_1LfdGaNaT6oTXVoYjlpAmD0w', 
#                             input={'command': 'ls -la'}, 
#                             name='bash', 
#                             type='tool_use')], 
#     model='deepseek-v4-flash', 
#     role='assistant', 
#     stop_reason='tool_use', 
#     stop_sequence=None, 
#     type='message', 
#     usage=Usage(cache_creation=None, 
#                 cache_creation_input_tokens=0, 
#                 cache_read_input_tokens=0, 
#                 input_tokens=275, 
#                 output_tokens=44, 
#                 server_tool_use=None, 
#                 service_tier='standard')
# )

# CompletedProcess(
# args='ls -la', 
# returncode=0, 
# stdout='total 224\ndrwxr-xr-x  20 jiqing  staff    640 Apr 24 23:06 .\ndrwxr-xr-x@ 21 jiqing  staff    672 Apr 24 16:09 ..\n-rw-r--r--@  1 jiqing  staff   6148 Apr 24 17:05 .DS_Store\n-rw-r--r--   1 jiqing  staff   2094 Apr 24 23:07 .env\n-rw-r--r--   1 jiqing  staff   2118 Apr 24 16:09 .env.example\ndrwxr-xr-x  14 jiqing  staff    448 Apr 24 16:10 .git\ndrwxr-xr-x   3 jiqing  staff     96 Apr 24 16:09 .github\n-rw-r--r--   1 jiqing  staff   5004 Apr 24 16:09 .gitignore\ndrwxr-xr-x@  8 jiqing  staff    256 Apr 24 16:37 .venv\n-rw-r--r--   1 jiqing  staff   1068 Apr 24 16:09 LICENSE\n-rw-r--r--   1 jiqing  staff  28889 Apr 24 16:09 README-ja.md\n-rw-r--r--   1 jiqing  staff  22541 Apr 24 16:09 README-zh.md\n-rw-r--r--   1 jiqing  staff  24427 Apr 24 16:09 README.md\ndrwxr-xr-x  16 jiqing  staff    512 Apr 24 16:09 agents\ndrwxr-xr-x   6 jiqing  staff    192 Apr 24 16:09 docs\n-rw-r--r--   1 jiqing  staff     50 Apr 24 16:09 requirements.txt\ndrwxr-xr-x   7 jiqing  staff    224 Apr 24 16:09 skills\ndrwxr-xr-x   4 jiqing  staff    128 Apr 26 07:44 src\ndrwxr-xr-x   4 jiqing  staff    128 Apr 24 16:09 tests\ndrwxr-xr-x  15 jiqing  staff    480 Apr 24 16:37 web\n', 
# stderr='')