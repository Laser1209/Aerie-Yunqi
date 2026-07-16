> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.bigmodel.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# GLM-5-Turbo

## 概览

**GLM-5-Turbo 是面向 OpenClaw 龙虾场景深度优化的基座模型。** 其从训练阶段就针对龙虾任务的核心需求进行专项优化，增强如工具调用、指令遵循、定时与持续性任务、长链路执行等核心能力，**使其在复杂、动态、长链路的任务中也真正具备可执行性。**

<CardGroup cols={3}>
  <Card title="定位" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/rocket.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=859cb435da005a3984eae8dc9f60ea7c)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/rocket.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=859cb435da005a3984eae8dc9f60ea7c)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />}>
    龙虾增强模型
  </Card>

<Card title="输入模态" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/arrow-down-right.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=088a58fa0b1a4048d5c6fab7841133c8)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/arrow-down-right.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=088a58fa0b1a4048d5c6fab7841133c8)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />}>
    文本
  </Card>

<Card title="输出模态" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/Skp28ct-clfAIOZo/resource/icon/arrow-down-left.svg?fit=max&auto=format&n=Skp28ct-clfAIOZo&q=85&s=1ed65b58aa7a484b387f01be25d99278)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/Skp28ct-clfAIOZo/resource/icon/arrow-down-left.svg?fit=max&auto=format&n=Skp28ct-clfAIOZo&q=85&s=1ed65b58aa7a484b387f01be25d99278)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />}>
    文本
  </Card>

<Card title="上下文窗口" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/Skp28ct-clfAIOZo/resource/icon/arrow-down-arrow-up.svg?fit=max&auto=format&n=Skp28ct-clfAIOZo&q=85&s=ccc051baa101b9a46d0d9bc5fad04877)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/Skp28ct-clfAIOZo/resource/icon/arrow-down-arrow-up.svg?fit=max&auto=format&n=Skp28ct-clfAIOZo&q=85&s=ccc051baa101b9a46d0d9bc5fad04877)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />}>
    200K
  </Card>

  <Card title="最大输出 Tokens" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/maximize.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=743c202becf04d91d943f9014a3fe67f)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/maximize.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=743c202becf04d91d943f9014a3fe67f)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />}>
    128K
  `</Card>`
`</CardGroup>`

## 能力支持

<CardGroup cols={3}>
  <Card title="思考模式" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/brain.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=b04e181006c02a51715f85395cd9735f)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/brain.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=b04e181006c02a51715f85395cd9735f)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />} href="/cn/guide/capabilities/thinking-mode">
    提供多种思考模式，覆盖不同任务需求
  </Card>

<Card title="流式输出" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/maximize.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=743c202becf04d91d943f9014a3fe67f)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/maximize.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=743c202becf04d91d943f9014a3fe67f)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />} href="/cn/guide/capabilities/streaming">
    支持实时流式响应，提升用户交互体验
  </Card>

  <Card title="Function Call" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/function.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=a597d8cdc054b4c0e39c08295f570c86)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/function.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=a597d8cdc054b4c0e39c08295f570c86)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />} href="/cn/guide/capabilities/function-calling">
    强大的工具调用能力，支持多种外部工具集成
  `</Card>`

<Card title="上下文缓存" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/database.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=93c0e1cf0ce93de9364ade5d1f49d992)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/database.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=93c0e1cf0ce93de9364ade5d1f49d992)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />} href="/cn/guide/capabilities/cache">
    智能缓存机制，优化长对话性能
  </Card>

<Card title="结构化输出" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/code.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=2f67130d1597ee0b68135487ec31662f)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/code.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=2f67130d1597ee0b68135487ec31662f)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />} href="/cn/guide/capabilities/struct-output">
    支持 JSON 等结构化格式输出，便于系统集成
  </Card>

<Card title="MCP" icon={<svg style={{maskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/box.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=e306f71ed712216941329f8a99ee858a)", WebkitMaskImage: "url(https://mintcdn.com/zhipu-ef7018ed/6jZAOYw-eXEZh1pv/resource/icon/box.svg?fit=max&auto=format&n=6jZAOYw-eXEZh1pv&q=85&s=e306f71ed712216941329f8a99ee858a)", maskRepeat: "no-repeat", maskPosition: "center center",}} className={"h-6 w-6 bg-primary dark:bg-primary-light !m-0 shrink-0"} />}>
    可灵活调用外部 MCP 工具与数据源，扩展应用场景
  </Card>
</CardGroup>

## 详细介绍

<Steps>
  <Step title="龙虾原生模型" stepNumber={1} titleSize="h3">
    从训练数据构造到优化目标设计，我们围绕真实Agent工作流，系统构造了多类龙虾任务场景，使模型在复杂、动态、长链路的任务中真正具备可执行性。重点增强了以下核心能力：

    ***Tool Calling——精准调用，不掉链子**：GLM-5-Turbo 强化了对外部工具与各类Skills的调用能力，在多步任务中更稳定、更可靠，让龙虾任务从对话走向执行。

    ***Instruction Following——复杂指令拆解更强**：对复杂、多层、长链路指令具备更强的理解和拆解能力，能够精准识别目标、规划步骤，并支持多智能体之间的协同分工。

    ***定时与持续性任务——更懂时间维度，长任务不中断**：针对定时触发、持续执行、长时间运行等场景进行了重点优化，能够更好理解时间维度上的要求，在复杂长任务中保持执行连续性。

    ***高吞吐长链路——执行更快更稳**：针对数据吞吐量大、逻辑链条长的龙虾任务，GLM-5-Turbo进一步提升了执行效率与响应稳定性，更适合进入真实业务流程。
  `</Step>`

  <Step title="龙虾场景基准 ZClawBench" stepNumber={2} titleSize="h3">
    随着龙虾 OpenClaw 的普及，如何评测模型在龙虾场景的能力成为全行业焦点。基于对 OpenClaw 大量真实用例的分析，我们发布**龙虾场景端到端 Agent 评测基准 ZClawBench**。

    当前 OpenClaw 的任务类型覆盖安装配置、代码开发、信息搜集、数据分析、内容创作等多元化任务，用户群体也从早期的开发者扩展到效率办公人群、金融从业者、运维工程师、内容创作者与研究分析人员等。同时，**Skills 的使用比例在短时间内从 26% 快速增长至 45%**，表明Agent能力正向模块化与技能化的生态方向演进。

    基于该基准的评测结果显示，GLM-5-Turbo 在 OpenClaw 场景中的表现相比 GLM-5 提升显著，在多项关键任务上整体领先于多家主流模型。

    ![Description](https://cdn.bigmodel.cn/markdown/1773634002851641c4f5371294c275d22ad1df8a5139b.png?attname=641c4f5371294c275d22ad1df8a5139b.png)

    ZClawBench的题库与测试轨迹已全面公开，欢迎业界共同验证与完善。`</Step>`
`</Steps>`

## 使用资源

<CardGroup cols={3}>
  <Card title="体验中心" href="https://bigmodel.cn/trialcenter/modeltrial/text?modelCode=glm-5-turbo">
    快速测试模型在业务场景上的效果
  </Card>

<Card title="接口文档" href="/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8">
    API 调用方式
  </Card>

  `<Card title="接入 OpenClaw" href="/cn/coding-plan/tool/openclaw#%E5%88%87%E6%8D%A2%E4%BD%BF%E7%94%A8-glm-5-turbo-%E6%A8%A1%E5%9E%8B">`
    在 OpenClaw 中调用 GLM-5-Turbo 的教程
  `</Card>`
`</CardGroup>`

## 调用示例

以下是完整的调用示例，帮助您快速上手 GLM-5-Turbo 模型。

<Tabs>
  <Tab title="cURL">
    **基础调用**

    ``bash theme={null}     curl -X POST "https://open.bigmodel.cn/api/paas/v4/chat/completions" \     -H "Content-Type: application/json" \     -H "Authorization: Bearer YOUR_API_KEY" \     -d '{         "model": "glm-5-turbo",         "messages": [             {                 "role": "user",                 "content": "作为一名营销专家，请为我的产品创作一个吸引人的口号"             },             {                 "role": "assistant",                 "content": "当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息"             },             {                 "role": "user",                 "content": "智谱开放平台"             }         ],         "thinking": {             "type": "enabled"         },         "max_tokens": 65536,         "temperature": 1.0     }'     ``

    **流式调用**

    ``bash theme={null}     curl -X POST "https://open.bigmodel.cn/api/paas/v4/chat/completions" \     -H "Content-Type: application/json" \     -H "Authorization: Bearer YOUR_API_KEY" \     -d '{         "model": "glm-5-turbo",         "messages": [             {                 "role": "user",                 "content": "作为一名营销专家，请为我的产品创作一个吸引人的口号"             },             {                 "role": "assistant",                 "content": "当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息"             },             {                 "role": "user",                 "content": "智谱开放平台"             }         ],         "thinking": {             "type": "enabled"         },         "stream": true,         "max_tokens": 65536,         "temperature": 1.0     }'     ``
  `</Tab>`

<Tab title="Python">
    **安装 SDK**

    ``bash theme={null}     # 安装最新版本     pip install zai-sdk     # 或指定版本     pip install zai-sdk==0.2.3     ``

    **验证安装**

    ``python theme={null}     import zai     print(zai.__version__)     ``

    **基础调用**

    ```python theme={null}
    from zai import ZhipuAiClient

    client = ZhipuAiClient(api_key="YOUR_API_KEY")  # 请填写您自己的 API Key

    response = client.chat.completions.create(
        model="glm-5-turbo",
        messages=[
            {"role": "user", "content": "作为一名营销专家，请为我的产品创作一个吸引人的口号"},
            {"role": "assistant", "content": "当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息"},
            {"role": "user", "content": "智谱开放平台"}
        ],
        thinking={
            "type": "enabled",    # 启用深度思考模式
        },
        max_tokens=65536,          # 最大输出 tokens
        temperature=1.0           # 控制输出的随机性
    )

    # 获取完整回复
    print(response.choices[0].message)
    ```

    **流式调用**

    ```python theme={null}
    from zai import ZhipuAiClient

    client = ZhipuAiClient(api_key="YOUR_API_KEY")  # 请填写您自己的 API Key

    response = client.chat.completions.create(
        model="glm-5-turbo",
        messages=[
            {"role": "user", "content": "作为一名营销专家，请为我的产品创作一个吸引人的口号"},
            {"role": "assistant", "content": "当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息"},
            {"role": "user", "content": "智谱开放平台"}
        ],
        thinking={
            "type": "enabled",    # 启用深度思考模式
        },
        stream=True,              # 启用流式输出
        max_tokens=65536,          # 最大输出tokens
        temperature=1.0           # 控制输出的随机性
    )

    # 流式获取回复
    for chunk in response:
        if chunk.choices[0].delta.reasoning_content:
            print(chunk.choices[0].delta.reasoning_content, end='', flush=True)

    if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end='', flush=True)
    ````</Tab>`

<Tab title="Java">
    **安装 SDK**

    **Maven**

    ``xml theme={null}     <dependency>         <groupId>ai.z.openapi</groupId>         <artifactId>zai-sdk</artifactId>         <version>0.3.5</version>     </dependency>     ``

    **Gradle (Groovy)**

    ``groovy theme={null}     implementation 'ai.z.openapi:zai-sdk:0.3.5'     ``

    **基础调用**

    ```java theme={null}
    import ai.z.openapi.ZhipuAiClient;
    import ai.z.openapi.service.model.ChatCompletionCreateParams;
    import ai.z.openapi.service.model.ChatCompletionResponse;
    import ai.z.openapi.service.model.ChatMessage;
    import ai.z.openapi.service.model.ChatMessageRole;
    import ai.z.openapi.service.model.ChatThinking;
    import java.util.Arrays;

    public class BasicChat {
        public static void main(String[] args) {
            // 初始化客户端
            ZhipuAiClient client = ZhipuAiClient.builder().ofZHIPU()
                .apiKey("YOUR_API_KEY")
                .build();

    // 创建聊天完成请求
            ChatCompletionCreateParams request = ChatCompletionCreateParams.builder()
                .model("glm-5-turbo")
                .messages(Arrays.asList(
                    ChatMessage.builder()
                        .role(ChatMessageRole.USER.value())
                        .content("作为一名营销专家，请为我的产品创作一个吸引人的口号")
                        .build(),
                    ChatMessage.builder()
                        .role(ChatMessageRole.ASSISTANT.value())
                        .content("当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息")
                        .build(),
                    ChatMessage.builder()
                        .role(ChatMessageRole.USER.value())
                        .content("智谱开放平台")
                        .build()
                ))
                .thinking(ChatThinking.builder().type("enabled").build())
                .maxTokens(65536)
                .temperature(1.0f)
                .build();

    // 发送请求
            ChatCompletionResponse response = client.chat().createChatCompletion(request);

    // 获取回复
            if (response.isSuccess()) {
                Object reply = response.getData().getChoices().get(0).getMessage();
                System.out.println("AI 回复: " + reply);
            } else {
                System.err.println("错误: " + response.getMsg());
            }
        }
    }
    ```

    **流式调用**

    ```java theme={null}
    import ai.z.openapi.ZhipuAiClient;
    import ai.z.openapi.service.model.ChatCompletionCreateParams;
    import ai.z.openapi.service.model.ChatCompletionResponse;
    import ai.z.openapi.service.model.ChatMessage;
    import ai.z.openapi.service.model.ChatMessageRole;
    import ai.z.openapi.service.model.ChatThinking;
    import ai.z.openapi.service.model.Delta;
    import java.util.Arrays;

    public class StreamingChat {
        public static void main(String[] args) {
            // 初始化客户端
            ZhipuAiClient client = ZhipuAiClient.builder().ofZHIPU()
                .apiKey("YOUR_API_KEY")
                .build();

    // 创建流式聊天完成请求
            ChatCompletionCreateParams request = ChatCompletionCreateParams.builder()
                .model("glm-5-turbo")
                .messages(Arrays.asList(
                    ChatMessage.builder()
                        .role(ChatMessageRole.USER.value())
                        .content("作为一名营销专家，请为我的产品创作一个吸引人的口号")
                        .build(),
                    ChatMessage.builder()
                        .role(ChatMessageRole.ASSISTANT.value())
                        .content("当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息")
                        .build(),
                    ChatMessage.builder()
                        .role(ChatMessageRole.USER.value())
                        .content("智谱开放平台")
                        .build()
                ))
                .thinking(ChatThinking.builder().type("enabled").build())
                .stream(true)  // 启用流式输出
                .maxTokens(65536)
                .temperature(1.0f)
                .build();

    ChatCompletionResponse response = client.chat().createChatCompletion(request);

    if (response.isSuccess()) {
                response.getFlowable().subscribe(
                    // Process streaming message data
                    data -> {
                        if (data.getChoices() != null && !data.getChoices().isEmpty()) {
                            Delta delta = data.getChoices().get(0).getDelta();
                            System.out.print(delta + "\n");
                        }
                    },
                    // Process streaming response error
                    error -> System.err.println("\nStream error: " + error.getMessage()),
                    // Process streaming response completion event
                    () -> System.out.println("\nStreaming response completed")
                );
            } else {
                System.err.println("Error: " + response.getMsg());
            }
        }
    }
    ````</Tab>`

<Tab title="Python(旧)">
    **更新 SDK 至 2.1.5.20250726**

    ```bash theme={null}
    # 安装最新版本
    pip install zhipuai

    # 或指定版本
    pip install zhipuai==2.1.5.20250726
    ```

    **基础调用**

    ```python theme={null}
    from zhipuai import ZhipuAI

    client = ZhipuAI(api_key="YOUR_API_KEY")  # 请填写您自己的 API Key

    response = client.chat.completions.create(
        model="glm-5-turbo",
        messages=[
            {"role": "user", "content": "作为一名营销专家，请为我的产品创作一个吸引人的口号"},
            {"role": "assistant", "content": "当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息"},
            {"role": "user", "content": "智谱开放平台"}
        ],
        thinking={
            "type": "enabled",
        },
        max_tokens=65536,
        temperature=1.0
    )

    # 获取完整回复
    print(response.choices[0].message)
    ```

    **流式调用**

    ```python theme={null}
    from zhipuai import ZhipuAI

    client = ZhipuAI(api_key="YOUR_API_KEY")  # 请填写您自己的 API Key

    response = client.chat.completions.create(
        model="glm-5-turbo",
        messages=[
            {"role": "user", "content": "作为一名营销专家，请为我的产品创作一个吸引人的口号"},
            {"role": "assistant", "content": "当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息"},
            {"role": "user", "content": "智谱开放平台"}
        ],
        thinking={
            "type": "enabled",
        },
        stream=True,              # 启用流式输出
        max_tokens=65536,
        temperature=1.0
    )

    # 流式获取回复
    for chunk in response:
        if chunk.choices[0].delta.reasoning_content:
            print(chunk.choices[0].delta.reasoning_content, end='', flush=True)

    if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end='', flush=True)
    `````</Tab></Tabs>``
