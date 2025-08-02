params = {
    "space_id": "02424c10-6360-4877-921d-49be8ad8bcee", 
}


def gen_ai_service(context, params = params, **custom):
    # import dependencies
    from langchain_ibm import ChatWatsonx
    from ibm_watsonx_ai import APIClient
    from ibm_watsonx_ai.foundation_models.utils import Tool, Toolkit
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.prebuilt import create_react_agent
    import json
    import requests

    model = "ibm/granite-3-3-8b-instruct"
    
    service_url = "https://us-south.ml.cloud.ibm.com"
    # Get credentials token
    credentials = {
        "url": service_url,
        "token": context.generate_token()
    }

    # Setup client
    client = APIClient(credentials)
    space_id = params.get("space_id")
    client.set.default_space(space_id)


    def decrypt_tool_secrets(secrets):
        url = "https://api.dataplatform.cloud.ibm.com"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f'Bearer {context.generate_token()}'
        }
    
        body = {
            "secrets": secrets,
            "space_id": space_id
        }
    
        response = requests.post(f'{url}/wx/v1-beta/utility_agent_tools/secret/decrypt', headers=headers, json=body)
    
        return response.json().get("secrets")
    
    encrypted_secrets = [
        "gcm-agent-tools-qHi31me0EfjVZVuGAnau05GBdpyvCVyV:4fDBNqstJdusiyeOR/efHg==;k552Ihu0wCk7u9/cq7GU1Q==:L3yRkrfSift+KrzGrorMJZKtCJ+nGSKaAys2DgpgPJYUwTLNFyfdTxioSg=="
    ]
    decrypted_secrets = decrypt_tool_secrets(encrypted_secrets)
    
    TavilySearch_apiKey = decrypted_secrets[0]
    

    def create_chat_model(watsonx_client):
        parameters = {
            "frequency_penalty": 0,
            "max_tokens": 2000,
            "presence_penalty": 0,
            "temperature": 0,
            "top_p": 1
        }

        chat_model = ChatWatsonx(
            model_id=model,
            url=service_url,
            space_id=space_id,
            params=parameters,
            watsonx_client=watsonx_client,
        )
        return chat_model
    
    def create_python_interpreter_tool(context):
        from langchain_core.tools import StructuredTool
    
        import ast
        import sys
        from io import StringIO
        import uuid
        import base64
        import os
    
        original_import = __import__
        
        def get_image_url(base_64_content, image_name, context):
            url = "https://api.dataplatform.cloud.ibm.com"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f'Bearer {context.get_token()}'
            }
    
            body = {
                "name": image_name,
                "blob": base_64_content
            }
    
            params = {
                "space_id": space_id
            }
    
            response = requests.post(f'{url}/wx/v1-beta/utility_agent_tools/resources', headers=headers, json=body, params=params)
    
            return response.json().get("uri")
    
        def patched_import(name, globals=None, locals=None, fromlist=(), level=0):
            module = original_import(name, globals, locals, fromlist, level)
        
            if name == "matplotlib.pyplot":
                sys.modules["matplotlib.pyplot"].show = pyplot_show
            return module
        
        def pyplot_show():
            pictureName = "plt-" + uuid.uuid4().hex + ".png"
            plt = sys.modules["matplotlib.pyplot"]
            plt.savefig(pictureName)
            with open(pictureName, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                print(f"base64image:{pictureName}:{str(encoded_string)}")
                os.remove(pictureName)
                plt.clf()
                plt.close("all")
        
        def init_imports():
            import builtins
            builtins.__import__ = patched_import
        
        def _executeAgentCode(code):
            old_stdout = sys.stdout
            try:
                full_code = "init_imports()\n\n" + code
                tree = ast.parse(full_code, mode="exec")
                compiled_code = compile(tree, 'agent_code', 'exec')
                namespace = {"init_imports": init_imports}
                redirected_output = sys.stdout = StringIO("")
                exec(compiled_code, namespace)
                value = redirected_output.getvalue()
                if (value.startswith("base64image")):
                    image_details = value.split(":")
                    image_name = image_details[1]
                    base_64_image = image_details[2]
                    image_url = get_image_url(base_64_image, image_name, context)
                    value = f"Result of executing generated Python code is an image:\n\nIMAGE({image_url})"
            except Exception as e:
                value = "Error while executing Python code:\n\n" + str(e)
            finally:
                sys.stdout = old_stdout
            return value
    
        tool_description = """Run Python code and return the console output. Use for isolated calculations, computations or data manipulation. In Python, the following modules are available: Use numpy, pandas, scipy and sympy for working with data. Use matplotlib to plot charts. Other Python libraries are also available -- however, prefer using the ones above. Prefer using qualified imports -- `import library; library.thing()` instead of `import thing from library`. Do not attempt to install libraries manually -- it will not work. Do not use this tool multiple times in a row, always write the full code you want to run in a single invocation. If you get an error running Python code, try to generate a better one that will pass. If the tool returns result that starts with IMAGE(, follow instructions for rendering images."""
        tool_schema = {
            "type": "object",
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {
                "code": {
                    "description": "Code to be executed.",
                    "type": "string"
                }
            },
            "required": ["code"]
        }
        
        return StructuredTool(
            name="PythonInterpreter",
            description = tool_description,
            func=_executeAgentCode,
            args_schema=tool_schema
        )
    
    
    def create_utility_agent_tool(tool_name, params, api_client, **kwargs):
        from langchain_core.tools import StructuredTool
        utility_agent_tool = Toolkit(
            api_client=api_client
        ).get_tool(tool_name)
    
        tool_description = utility_agent_tool.get("description")
    
        if (kwargs.get("tool_description")):
            tool_description = kwargs.get("tool_description")
        elif (utility_agent_tool.get("agent_description")):
            tool_description = utility_agent_tool.get("agent_description")
        
        tool_schema = utility_agent_tool.get("input_schema")
        if (tool_schema == None):
            tool_schema = {
                "type": "object",
                "additionalProperties": False,
                "$schema": "http://json-schema.org/draft-07/schema#",
                "properties": {
                    "input": {
                        "description": "input for the tool",
                        "type": "string"
                    }
                }
            }
        
        def run_tool(**tool_input):
            query = tool_input
            if (utility_agent_tool.get("input_schema") == None):
                query = tool_input.get("input")
    
            results = utility_agent_tool.run(
                input=query,
                config=params
            )
            
            return results.get("output")
        
        return StructuredTool(
            name=tool_name,
            description = tool_description,
            func=run_tool,
            args_schema=tool_schema
        )
    
    
    def create_custom_tool(tool_name, tool_description, tool_code, tool_schema, tool_params):
        from langchain_core.tools import StructuredTool
        import ast
    
        def call_tool(**kwargs):
            tree = ast.parse(tool_code, mode="exec")
            custom_tool_functions = [ x for x in tree.body if isinstance(x, ast.FunctionDef) ]
            function_name = custom_tool_functions[0].name
            compiled_code = compile(tree, 'custom_tool', 'exec')
            namespace = tool_params if tool_params else {}
            exec(compiled_code, namespace)
            return namespace[function_name](**kwargs)
            
        tool = StructuredTool(
            name=tool_name,
            description = tool_description,
            func=call_tool,
            args_schema=tool_schema
        )
        return tool
    
    def create_custom_tools():
        custom_tools = []
    

    def create_tools(inner_client, context):
        tools = []
        tools.append(create_python_interpreter_tool(context))
        
        config = None
        tools.append(create_utility_agent_tool("GoogleSearch", config, inner_client))
        config = {
            "maxResults": 5
        }
        tools.append(create_utility_agent_tool("Wikipedia", config, inner_client))
        config = {
        }
        tools.append(create_utility_agent_tool("WebCrawler", config, inner_client))
        config = {
        }
        tools.append(create_utility_agent_tool("DuckDuckGo", config, inner_client))
        config = {
            "maxResults": 10,
            "apiKey": TavilySearch_apiKey
        }
        tools.append(create_utility_agent_tool("TavilySearch", config, inner_client))
        return tools
    
    def create_agent(model, tools, messages):
        memory = MemorySaver()
        instructions = """# Notes
- When a tool is required to answer the user's query, respond only with <|tool_call|> followed by a JSON list of tools used.
- If a tool does not exist in the provided list of tools, notify the user that you do not have the ability to fulfill the request.
You are a smart and helpful Recipe Preparation Agent.
1.The user will give you a list of ingredients they have.
2.Your job is to suggest atleast two three recipes that can be made using those ingredients.
3.If exact ingredients are not enough, suggest smart substitutions.
4.Adapt recipe steps to use only what the user has.
5.If something important is missing, ask the user if they want a substitute or a simpler recipe.
6.Provide clear, step-by-step cooking instructions in simple language.
7.Mention expected prep time and cooking time.
8.If the user has dietary restrictions or preferences (e.g., vegan, gluten-free), respect them and prepare accordingly .
9.Be friendly, helpful, and focused on reducing food waste.


"""
        for message in messages:
            if message["role"] == "system":
                instructions += message["content"]
        graph = create_react_agent(model, tools=tools, checkpointer=memory, state_modifier=instructions)
        return graph
    
    def convert_messages(messages):
        converted_messages = []
        for message in messages:
            if (message["role"] == "user"):
                converted_messages.append(HumanMessage(content=message["content"]))
            elif (message["role"] == "assistant"):
                converted_messages.append(AIMessage(content=message["content"]))
        return converted_messages

    def generate(context):
        payload = context.get_json()
        messages = payload.get("messages")
        inner_credentials = {
            "url": service_url,
            "token": context.get_token()
        }

        inner_client = APIClient(inner_credentials)
        model = create_chat_model(inner_client)
        tools = create_tools(inner_client, context)
        agent = create_agent(model, tools, messages)
        
        generated_response = agent.invoke(
            { "messages": convert_messages(messages) },
            { "configurable": { "thread_id": "42" } }
        )

        last_message = generated_response["messages"][-1]
        generated_response = last_message.content

        execute_response = {
            "headers": {
                "Content-Type": "application/json"
            },
            "body": {
                "choices": [{
                    "index": 0,
                    "message": {
                       "role": "assistant",
                       "content": generated_response
                    }
                }]
            }
        }

        return execute_response

    def generate_stream(context):
        print("Generate stream", flush=True)
        payload = context.get_json()
        headers = context.get_headers()
        is_assistant = headers.get("X-Ai-Interface") == "assistant"
        messages = payload.get("messages")
        inner_credentials = {
            "url": service_url,
            "token": context.get_token()
        }
        inner_client = APIClient(inner_credentials)
        model = create_chat_model(inner_client)
        tools = create_tools(inner_client, context)
        agent = create_agent(model, tools, messages)

        response_stream = agent.stream(
            { "messages": messages },
            { "configurable": { "thread_id": "42" } },
            stream_mode=["updates", "messages"]
        )

        for chunk in response_stream:
            chunk_type = chunk[0]
            finish_reason = ""
            usage = None
            if (chunk_type == "messages"):
                message_object = chunk[1][0]
                if (message_object.type == "AIMessageChunk" and message_object.content != ""):
                    message = {
                        "role": "assistant",
                        "content": message_object.content
                    }
                else:
                    continue
            elif (chunk_type == "updates"):
                update = chunk[1]
                if ("agent" in update):
                    agent = update["agent"]
                    agent_result = agent["messages"][0]
                    if (agent_result.additional_kwargs):
                        kwargs = agent["messages"][0].additional_kwargs
                        tool_call = kwargs["tool_calls"][0]
                        if (is_assistant):
                            message = {
                                "role": "assistant",
                                "step_details": {
                                    "type": "tool_calls",
                                    "tool_calls": [
                                        {
                                            "id": tool_call["id"],
                                            "name": tool_call["function"]["name"],
                                            "args": tool_call["function"]["arguments"]
                                        }
                                    ] 
                                }
                            }
                        else:
                            message = {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": tool_call["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tool_call["function"]["name"],
                                            "arguments": tool_call["function"]["arguments"]
                                        }
                                    }
                                ]
                            }
                    elif (agent_result.response_metadata):
                        # Final update
                        message = {
                            "role": "assistant",
                            "content": agent_result.content
                        }
                        finish_reason = agent_result.response_metadata["finish_reason"]
                        if (finish_reason): 
                            message["content"] = ""

                        usage = {
                            "completion_tokens": agent_result.usage_metadata["output_tokens"],
                            "prompt_tokens": agent_result.usage_metadata["input_tokens"],
                            "total_tokens": agent_result.usage_metadata["total_tokens"]
                        }
                elif ("tools" in update):
                    tools = update["tools"]
                    tool_result = tools["messages"][0]
                    if (is_assistant):
                        message = {
                            "role": "assistant",
                            "step_details": {
                                "type": "tool_response",
                                "id": tool_result.id,
                                "tool_call_id": tool_result.tool_call_id,
                                "name": tool_result.name,
                                "content": tool_result.content
                            }
                        }
                    else:
                        message = {
                            "role": "tool",
                            "id": tool_result.id,
                            "tool_call_id": tool_result.tool_call_id,
                            "name": tool_result.name,
                            "content": tool_result.content
                        }
                else:
                    continue

            chunk_response = {
                "choices": [{
                    "index": 0,
                    "delta": message
                }]
            }
            if (finish_reason):
                chunk_response["choices"][0]["finish_reason"] = finish_reason
            if (usage):
                chunk_response["usage"] = usage
            yield chunk_response

    return generate, generate_stream
