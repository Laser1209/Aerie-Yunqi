> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建对话请求（OpenAI）

> Creates a model response for the given chat conversation.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /chat/completions:
    post:
      tags:
        - Chat Completions
      summary: Chat Completions
      description: Creates a model response for the given chat conversation.
      operationId: chat-completions
      requestBody:
        content:
          application/json:
            schema:
              oneOf:
                - $ref: '#/components/schemas/ChatCompletionRequest'
                - $ref: '#/components/schemas/ChatCompletionVLMRequest'
      responses:
        '200':
          description: '200'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ChatCompletionResponse'
            text/event-stream:
              schema:
                $ref: '#/components/schemas/ChatCompletionStream'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    ChatCompletionRequest:
      title: LLM
      type: object
      required:
        - model
        - messages
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          example: Qwen/Qwen3-32B
          enum:
            - deepseek-ai/DeepSeek-R1
            - deepseek-ai/DeepSeek-V3
            - deepseek-ai/DeepSeek-V3.1
            - deepseek-ai/DeepSeek-V3.1-Terminus
            - deepseek-ai/DeepSeek-V3.2-Exp
            - deepseek-ai/DeepSeek-V3.2
            - deepseek-ai/deepseek-vl2
            - deepseek-ai/DeepSeek-V4-Flash
            - deepseek-ai/DeepSeek-V4-Pro
            - nex-agi/DeepSeek-V3.1-Nex-N1
            - baidu/ERNIE-4.5-300B-A47B
            - THUDM/GLM-4-32B-0414
            - THUDM/GLM-4-9B-0414
            - zai-org/GLM-4.5
            - zai-org/GLM-4.5-Air
            - zai-org/GLM-4.5V
            - zai-org/GLM-5
            - zai-org/GLM-5.1
            - zai-org/GLM-4.7
            - zai-org/GLM-4.6
            - zai-org/GLM-4.6V
            - zai-org/GLM-5V-Turbo
            - THUDM/GLM-Z1-32B-0414
            - THUDM/GLM-Z1-9B-0414
            - tencent/Hunyuan-A13B-Instruct
            - tencent/Hunyuan-MT-7B
            - tencent/Hy3-preview
            - moonshotai/Kimi-K2.5
            - moonshotai/Kimi-K2.6
            - moonshotai/Kimi-K2-Instruct
            - moonshotai/Kimi-K2-Instruct-0905
            - moonshotai/Kimi-K2-Thinking
            - inclusionAI/Ling-flash-2.0
            - inclusionAI/Ling-mini-2.0
            - inclusionAI/Ring-flash-2.0
            - meta-llama/Meta-Llama-3.1-8B-Instruct
            - MiniMaxAI/MiniMax-M2.5
            - MiniMaxAI/MiniMax-M2.1
            - Qwen/Qwen2.5-14B-Instruct
            - Qwen/Qwen2.5-32B-Instruct
            - Qwen/Qwen2.5-72B-Instruct
            - Qwen/Qwen2.5-72B-Instruct-128K
            - Qwen/Qwen2.5-7B-Instruct
            - Qwen/Qwen2.5-VL-7B-Instruct
            - Qwen/Qwen3-14B
            - Qwen/Qwen3-235B-A22B
            - Qwen/Qwen3-235B-A22B-Instruct-2507
            - Qwen/Qwen3-235B-A22B-Thinking-2507
            - Qwen/Qwen3-30B-A3B-Instruct-2507
            - Qwen/Qwen3-30B-A3B-Thinking-2507
            - Qwen/Qwen3-32B
            - Qwen/Qwen3-8B
            - Qwen/Qwen3-Coder-30B-A3B-Instruct
            - Qwen/Qwen3-Coder-480B-A35B-Instruct
            - Qwen/Qwen3-Next-80B-A3B-Instruct
            - Qwen/Qwen3-Next-80B-A3B-Thinking
            - Qwen/Qwen3-Omni-30B-A3B-Captioner
            - Qwen/Qwen3-Omni-30B-A3B-Instruct
            - Qwen/Qwen3-Omni-30B-A3B-Thinking
            - Qwen/Qwen3.5-122B-A10B
            - Qwen/Qwen3.5-27B
            - Qwen/Qwen3.5-35B-A3B
            - Qwen/Qwen3.5-397B-A17B
            - Qwen/Qwen3.5-9B
            - Qwen/Qwen3.6-27B
            - Qwen/Qwen3.6-35B-A3B
            - ByteDance-Seed/Seed-OSS-36B-Instruct
            - google/gemma-4-26B-A4B-it
            - google/gemma-4-31B-it
            - openai/gpt-oss-120b
            - openai/gpt-oss-20b
        messages:
          type: array
          description: A list of messages comprising the conversation so far.
          items:
            type: object
            properties:
              role:
                type: string
                description: >-
                  The role of the messages author. Choice between: system, user,
                  or assistant.
                example: user
                default: user
                enum:
                  - user
                  - assistant
                  - system
              content:
                oneOf:
                  - type: string
                    description: The contents of the message.
                    example: >-
                      What opportunities and challenges will the Chinese large
                      model industry face in 2025?
                    default: >-
                      What opportunities and challenges will the Chinese large
                      model industry face in 2025?
            required:
              - role
              - content
          minItems: 1
          maxItems: 10
        stream:
          type: boolean
          description: >-
            If set, tokens are returned as Server-Sent Events as they are made
            available. Stream terminates with `data: [DONE]`
          example: false
        max_tokens:
          type: integer
          description: >
            The maximum number of tokens to generate. Ensure that input tokens +
            max_tokens do not exceed the model’s context window. As some
            services are still being updated, avoid setting max_tokens to the
            window’s upper bound; reserve ~10k tokens as buffer for input and
            system overhead. See Models(https://cloud.siliconflow.cn/models) for
            details. 
          example: 4096
        enable_thinking:
          type: boolean
          description: >
            Switches between thinking and non-thinking modes. Default is True. 
            This field supports the following models: 

                - Qwen/Qwen3-8B
                - Qwen/Qwen3-14B
                - Qwen/Qwen3-32B
                - wen/Qwen3-30B-A3B
                - Qwen/Qwen3-235B-A22B
                - tencent/Hunyuan-A13B-Instruct
                - zai-org/GLM-5V-Turbo
                - zai-org/GLM-4.6V
                - zai-org/GLM-4.5V
                - deepseek-ai/DeepSeek-V3.1
                - deepseek-ai/DeepSeek-V3.1-Terminus
                - deepseek-ai/DeepSeek-V3.2-Exp
                - deepseek-ai/DeepSeek-V3.2

            If you want to use the function call feature for
            deepseek-ai/DeepSeek-V3.1, you need to set enable_thinking to
            false. 
          example: false
        thinking_budget:
          type: integer
          description: >-
            Maximum number of tokens for chain-of-thought output. This field
            applies to all Reasoning models.
          example: 4096
          default: 4096
          minimum: 128
          maximum: 32768
        min_p:
          type: number
          description: >-
            Dynamic filtering threshold that adapts based on token
            probabilities.This field only applies to Qwen3.
          format: float
          example: 0.05
          minimum: 0
          maximum: 1
        stop:
          description: >
            Up to 4 sequences where the API will stop generating further tokens.
            The returned text will not contain the stop sequence.
          nullable: true
          oneOf:
            - type: string
              example: null
              nullable: true
            - type: array
              minItems: 1
              maxItems: 4
              items:
                type: string
                example: 'null'
        temperature:
          type: number
          description: Determines the degree of randomness in the response.
          format: float
          example: 0.7
        top_p:
          type: number
          description: >-
            The `top_p` (nucleus) parameter is used to dynamically adjust the
            number of choices for each predicted token based on the cumulative
            probabilities.
          format: float
          example: 0.7
          default: 0.7
        top_k:
          type: number
          format: float
          example: 50
        frequency_penalty:
          type: number
          format: float
          example: 0.5
        'n':
          type: integer
          description: Number of generations to return
          example: 1
        response_format:
          type: object
          description: An object specifying the format that the model must output.
          properties:
            type:
              type: string
              description: The type of the response format.
              example: text
        tools:
          type: array
          description: >
            A list of tools the model may call. Currently, only functions are
            supported as a tool. Use this to provide a list of functions the
            model may generate JSON inputs for. A max of 128 functions are
            supported.
          items:
            $ref: '#/components/schemas/ChatCompletionTool'
    ChatCompletionVLMRequest:
      title: VLM
      type: object
      required:
        - model
        - messages
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          example: Qwen/Qwen3-VL-32B-Instruct
          default: Qwen/Qwen3-VL-32B-Instruct
          enum:
            - Qwen/Qwen3-VL-32B-Instruct
            - Qwen/Qwen3-VL-32B-Thinking
            - Qwen/Qwen3-VL-8B-Instruct
            - Qwen/Qwen3-VL-8B-Thinking
            - Qwen/Qwen3-VL-235B-A22B-Instruct
            - Qwen/Qwen3-VL-235B-A22B-Thinking
            - Qwen/Qwen3-VL-30B-A3B-Thinking
            - Qwen/Qwen3-VL-30B-A3B-Instruct
            - deepseek-ai/deepseek-vl2
            - zai-org/GLM-5V-Turbo
            - zai-org/GLM-4.6V
            - zai-org/GLM-4.5V
            - Qwen/Qwen2.5-VL-7B-Instruct
            - Qwen/Qwen3-Omni-30B-A3B-Captioner
            - Qwen/Qwen3-Omni-30B-A3B-Instruct
            - Qwen/Qwen3-Omni-30B-A3B-Thinking
        messages:
          type: array
          description: A list of messages comprising the conversation so far.
          items:
            type: object
            properties:
              role:
                type: string
                description: >-
                  The role of the messages author. Choice between: system, user,
                  or assistant.
                example: user
                default: user
                enum:
                  - user
                  - assistant
                  - system
              content:
                oneOf:
                  - type: array
                    description: >-
                      An array of content parts with a defined type, each can be
                      of type `text` or `image_url` when passing in images. You
                      can pass multiple images by adding multiple `image_url`
                      content parts. The Qwen3-Omni series supports `video_url`
                      and `audio_url`, enabling the recognition of video and
                      audio content. The Qwen3-VL model also supports
                      `video_url`, allowing it to recognize video content.
                      Recommend videos and audio within 30 seconds.
                    items:
                      $ref: >-
                        #/components/schemas/ChatCompletionRequestUserMessageContentPart
                    minItems: 1
            required:
              - role
              - content
          minItems: 1
          maxItems: 10
        stream:
          type: boolean
          description: >-
            If set, tokens are returned as Server-Sent Events as they are made
            available. Stream terminates with `data: [DONE]`
          example: false
          default: false
        max_tokens:
          type: integer
          description: >
            The maximum number of tokens to generate. Ensure that input tokens +
            max_tokens do not exceed the model’s context window. As some
            services are still being updated, avoid setting max_tokens to the
            window’s upper bound; reserve ~10k tokens as buffer for input and
            system overhead. See Models(https://cloud.siliconflow.cn/models) for
            details. 
        stop:
          description: >
            Up to 4 sequences where the API will stop generating further tokens.
            The returned text will not contain the stop sequence.
          default: []
          nullable: true
          oneOf:
            - type: array
              minItems: 1
              maxItems: 4
              items:
                type: string
                example: 'null'
            - type: string
              default: <|endoftext|>
              example: |+

              nullable: true
            - type: string
              default: <|endoftext|>
              example: ''
              nullable: true
        temperature:
          type: number
          description: Determines the degree of randomness in the response.
          format: float
          example: 0.7
          default: 0.7
        top_p:
          type: number
          description: >-
            The `top_p` (nucleus) parameter is used to dynamically adjust the
            number of choices for each predicted token based on the cumulative
            probabilities.
          format: float
          example: 0.7
          default: 0.7
        top_k:
          type: number
          format: float
          example: 50
          default: 50
        frequency_penalty:
          type: number
          format: float
          example: 0.5
          default: 0.5
        'n':
          type: integer
          description: Number of generations to return
          example: 1
          default: 1
        response_format:
          type: object
          description: An object specifying the format that the model must output.
          properties:
            type:
              type: string
              description: The type of the response format.
              example: text
    ChatCompletionResponse:
      type: object
      properties:
        id:
          type: string
        choices:
          $ref: '#/components/schemas/ChatCompletionChoicesData'
        usage:
          $ref: '#/components/schemas/UsageData'
        created:
          type: integer
        model:
          type: string
        object:
          type: string
          enum:
            - chat.completion
    ChatCompletionStream:
      type: object
      properties:
        id:
          type: string
        choices:
          $ref: '#/components/schemas/ChatCompletionChoicesData'
        created:
          type: integer
        model:
          type: string
        object:
          type: string
          enum:
            - chat.completion.chunk
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
    ChatCompletionTool:
      type: object
      properties:
        type:
          type: string
          enum:
            - function
          description: The type of the tool. Currently, only `function` is supported.
        function:
          $ref: '#/components/schemas/FunctionObject'
      required:
        - type
        - function
    ChatCompletionRequestUserMessageContentPart:
      oneOf:
        - $ref: '#/components/schemas/ChatCompletionRequestMessageContentPartImage'
        - $ref: '#/components/schemas/ChatCompletionRequestMessageContentPartText'
      x-oaiExpandable: true
    ChatCompletionChoicesData:
      type: array
      items:
        type: object
        properties:
          message:
            type: object
            properties:
              role:
                type: string
                example: assistant
              content:
                type: string
              reasoning_content:
                description: >-
                  Only the DeepSeek-R1 series models support reasoning_content.
                  This part returns the reasoning content, which is at the same
                  level as the content. In each round of the conversation, the
                  model outputs the reasoning chain content (reasoning_content)
                  and the final answer (content). In the next round of the
                  conversation, the reasoning chain content from previous rounds
                  will not be appended to the context.
                type: string
              tool_calls:
                type: array
                description: The tool calls generated by the model, such as function calls.
                items:
                  $ref: '#/components/schemas/ChatCompletionMessageToolCall'
          finish_reason:
            $ref: '#/components/schemas/FinishReason'
    UsageData:
      type: object
      properties:
        prompt_tokens:
          type: integer
        completion_tokens:
          type: integer
        total_tokens:
          type: integer
    FunctionObject:
      type: object
      properties:
        description:
          type: string
          description: >-
            A description of what the function does, used by the model to choose
            when and how to call the function.
        name:
          type: string
          description: >-
            The name of the function to be called. Must be a-z, A-Z, 0-9, or
            contain underscores and dashes, with a maximum length of 64.
        parameters:
          $ref: '#/components/schemas/FunctionParameters'
        strict:
          type: boolean
          nullable: true
          default: false
          description: >-
            Whether to enable strict schema adherence when generating the
            function call. If set to true, the model will follow the exact
            schema defined in the `parameters` field. Only a subset of JSON
            Schema is supported when `strict` is `true`. Learn more about
            Structured Outputs in the [function calling
            guide](docs/guides/function-calling).
      required:
        - name
    ChatCompletionRequestMessageContentPartImage:
      type: object
      title: Image content part
      properties:
        type:
          type: string
          enum:
            - image_url
          description: The type of the content part.
          default: image_url
        image_url:
          type: object
          properties:
            url:
              type: string
              description: >-
                Either a URL of the image or the base64 encoded image data.
                TeleAI/TeleMM only support the base64 encoded image data.
              default: >-
                https://sf-maas.s3.us-east-1.amazonaws.com/images/recu6XreBFQ0st.png
              example: >-
                https://sf-maas.s3.us-east-1.amazonaws.com/images/recu6XreBFQ0st.png
            detail:
              type: string
              description: Specifies the detail level of the image.
              enum:
                - auto
                - low
                - high
              default: auto
          required:
            - url
      required:
        - type
        - image_url
    ChatCompletionRequestMessageContentPartText:
      type: object
      title: Text content part
      properties:
        type:
          type: string
          enum:
            - text
          description: The type of the content part.
          default: text
        text:
          type: string
          description: The text content.
          default: Describe this picture.
      required:
        - type
        - text
    ChatCompletionMessageToolCall:
      type: object
      properties:
        id:
          type: string
          description: The ID of the tool call.
        type:
          type: string
          enum:
            - function
          description: The type of the tool. Currently, only `function` is supported.
        function:
          type: object
          description: The function that the model called.
          properties:
            name:
              type: string
              description: The name of the function to call.
            arguments:
              type: string
              description: >-
                The arguments to call the function with, as generated by the
                model in JSON format. Note that the model does not always
                generate valid JSON, and may hallucinate parameters not defined
                by your function schema. Validate the arguments in your code
                before calling your function.
          required:
            - name
            - arguments
      required:
        - id
        - type
        - function
    FinishReason:
      type: string
      enum:
        - stop
        - eos
        - length
        - tool_calls
    FunctionParameters:
      type: object
      description: >-
        The parameters the functions accepts, described as a JSON Schema object.
        See the [guide](/guides/function_calling) for examples, and the [JSON
        Schema reference](https://json-schema.org/understanding-json-schema/)
        for documentation about the format. 


        Omitting `parameters` defines a function with an empty parameter list.
      additionalProperties: true
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````




> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建对话请求（Anthropic）

> Creates a model response for the given chat conversation.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /messages:
    post:
      tags:
        - messages
      summary: Chat Completions
      description: Creates a model response for the given chat conversation.
      operationId: chat-completions
      requestBody:
        content:
          application/json:
            schema:
              oneOf:
                - $ref: '#/components/schemas/ChatMessagesRequest'
      responses:
        '200':
          description: '200'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MessgesResponse'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
      security:
        - bearerAuth: []
        - apiKey: []
components:
  schemas:
    ChatMessagesRequest:
      title: LLM
      type: object
      required:
        - model
        - messages
        - max_tokens
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          example: moonshotai/Kimi-K2-Instruct
          default: null
          enum:
            - deepseek-ai/DeepSeek-V3.2
            - deepseek-ai/DeepSeek-V3.2-Exp
            - deepseek-ai/DeepSeek-V3.1-Terminus
            - deepseek-ai/DeepSeek-V3.1
            - deepseek-ai/DeepSeek-V3
            - nex-agi/DeepSeek-V3.1-Nex-N1
            - moonshotai/Kimi-K2.5
            - moonshotai/Kimi-K2-Instruct-0905
            - moonshotai/Kimi-K2-Instruct
            - moonshotai/Kimi-K2-Thinking
            - baidu/ERNIE-4.5-300B-A47B
        messages:
          type: array
          description: A list of messages comprising the conversation so far.
          items:
            type: object
            properties:
              role:
                type: string
                description: 'The role of the messages author. Choice between: system, user.'
                example: user
                enum:
                  - user
                  - system
                  - assistant
              content:
                oneOf:
                  - type: string
                    description: The contents of the message.
                    example: >-
                      What opportunities and challenges will the Chinese large
                      model industry face in 2025?
            required:
              - role
              - content
          minItems: 1
          maxItems: 10
        system:
          allOf:
            - anyOf:
                - type: string
                - items:
                    $ref: '#/components/schemas/RequestTextBlock'
                  type: array
              description: >-
                System prompt.


                A system prompt is a way of providing context and instructions
                to llm, such as specifying a particular goal or role. 
              title: System
        stop_sequences:
          allOf:
            - description: >-
                Custom text sequences that will cause the model to stop
                generating.


                Our models will normally stop when they have naturally completed
                their turn, which will result in a response `stop_reason` of
                `"end_turn"`.


                If you want the model to stop generating when it encounters
                custom strings of text, you can use the `stop_sequences`
                parameter. If the model encounters one of the custom sequences,
                the response `stop_reason` value will be `"stop_sequence"` and
                the response `stop_sequence` value will contain the matched stop
                sequence.
              items:
                type: string
              title: Stop Sequences
              type: array
        stream:
          type: boolean
          description: >-
            If set, tokens are returned as Server-Sent Events as they are made
            available. Stream terminates with `data: [DONE]`
          example: true
        max_tokens:
          type: integer
          description: >-
            The maximum number of tokens to generate before stopping.


            Note that our models may stop _before_ reaching this maximum. This
            parameter only specifies the absolute maximum number of tokens to
            generate.


            Different models have different maximum values for this parameter. 
            See
            [models](https://docs.siliconflow.com/cn/userguide/capabilities/text-generation)
            for details.
          example: 8192
        temperature:
          type: number
          description: Determines the degree of randomness in the response.
          format: float
          example: 0.7
          maximum: 2
          minimum: 0
        top_p:
          type: number
          description: >-
            The `top_p` (nucleus) parameter is used to dynamically adjust the
            number of choices for each predicted token based on the cumulative
            probabilities.
          format: float
          example: 0.7
          minimum: 0.1
          maximum: 1
        top_k:
          type: number
          format: float
          example: 50
          minimum: 0
          maximum: 50
        tools:
          type: array
          description: |
            Each tool definition includes:


              * `name`: Name of the tool.

              * `description`: Optional, but strongly-recommended
              description of the tool.

              * `input_schema`: [JSON
              schema](https://json-schema.org/draft/2020-12) for the
              tool `input` shape that the model will produce in
              `tool_use` output content blocks.
          items:
            $ref: '#/components/schemas/MessagesTool'
        tool_choice:
          allOf:
            - description: >-
                How the model should use the provided tools. The model can use a
                specific tool, any available tool, decide by itself, or not use
                tools at all.
              discriminator:
                mapping:
                  auto:
                    $ref: '#/components/schemas/ToolChoiceAuto'
                  none:
                    $ref: '#/components/schemas/ToolChoiceNone'
                  tool:
                    $ref: '#/components/schemas/ToolChoiceTool'
                propertyName: type
              oneOf:
                - $ref: '#/components/schemas/ToolChoiceAuto'
                - $ref: '#/components/schemas/ToolChoiceTool'
                - $ref: '#/components/schemas/ToolChoiceNone'
    MessgesResponse:
      type: object
      properties:
        id:
          type: string
        type:
          default: message
          description: |-
            Object type.

            For Messages, this is always `"message"`.
          enum:
            - message
          title: Type
          type: string
        role:
          default: assistant
          description: |-
            Conversational role of the generated message.

            This will always be `"assistant"`.
          enum:
            - assistant
          title: Role
          type: string
        content:
          description: >-
            Content generated by the model.


            This is an array of content blocks, each of which has a `type` that
            determines its shape.


            Example:


            ```json

            [{"type": "text", "text": "Hi"}]

            ```


            If the request input `messages` ended with an `assistant` turn, then
            the response `content` will continue directly from that last turn.
            You can use this to constrain the model's output.


            For example, if the input `messages` were:

            ```json

            [
              {"role": "user", "content": "What's the Greek name for Sun? (A) Sol (B) Helios (C) Sun"},
              {"role": "assistant", "content": "The best answer is ("}
            ]

            ```


            Then the response `content` might be:


            ```json

            [{"type": "text", "text": "B)"}]

            ```
          items:
            oneOf:
              - $ref: '#/components/schemas/ResponseToolUseBlock'
          title: Content
          type: array
        model:
          description: The model that handled the request.
          title: Model
          type: string
        stop_reason:
          anyOf:
            - enum:
                - end_turn
                - max_tokens
                - tool_use
                - refusal
              type: string
          description: >-
            The reason that we stopped.


            This may be one the following values:

            * `"end_turn"`: the model reached a natural stopping point or one of
            your provided custom `stop_sequences` was generated

            * `"max_tokens"`: we exceeded the requested `max_tokens` or the
            model's maximum

            * `"tool_use"`: the model invoked one or more tools

            * `"refusal"`: when streaming classifiers intervene to handle
            potential policy violations


            In non-streaming mode this value is always non-null. In streaming
            mode, it is null in the `message_start` event and non-null
            otherwise.
          title: Stop Reason
        stop_sequence:
          anyOf:
            - type: string
          default: null
          description: >-
            Which custom stop sequence was generated, if any.


            This value will be a non-null string if one of your custom stop
            sequences was generated.
          title: Stop Sequence
        usage:
          allOf:
            - $ref: '#/components/schemas/Usage'
              description: Billing and rate-limit usage.
              examples:
                - input_tokens: 2095
                  output_tokens: 503
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
    RequestTextBlock:
      additionalProperties: false
      properties:
        text:
          minLength: 1
          title: Text
          type: string
        type:
          enum:
            - text
          title: Type
          type: string
      required:
        - text
        - type
      title: Text
      type: object
    MessagesTool:
      type: object
      properties:
        name:
          description: >-
            Name of the tool.


            This is how the tool will be called by the model and in `tool_use`
            blocks.
          title: Name
          type: string
        input_schema:
          $ref: '#/components/schemas/InputSchema'
          description: >-
            [JSON schema](https://json-schema.org/draft/2020-12) for this tool's
            input.

            This defines the shape of the `input` that your tool accepts and
            that the model will produce.
      required:
        - name
        - input_schema
    ToolChoiceAuto:
      additionalProperties: false
      description: The model will automatically decide whether to use tools.
      properties:
        disable_parallel_tool_use:
          description: >-
            Whether to disable parallel tool use.


            Defaults to `false`. If set to `true`, the model will output at most
            one tool use.
          title: Disable Parallel Tool Use
          type: boolean
        type:
          enum:
            - auto
          title: Type
          type: string
      required:
        - type
      title: Auto
      type: object
    ToolChoiceNone:
      additionalProperties: false
      description: The model will not be allowed to use tools.
      properties:
        type:
          enum:
            - none
          title: Type
          type: string
      required:
        - type
      title: None
      type: object
    ToolChoiceTool:
      additionalProperties: false
      description: The model will use the specified tool with `tool_choice.name`.
      properties:
        disable_parallel_tool_use:
          description: >-
            Whether to disable parallel tool use.


            Defaults to `false`. If set to `true`, the model will output exactly
            one tool use.
          title: Disable Parallel Tool Use
          type: boolean
        name:
          description: The name of the tool to use.
          title: Name
          type: string
        type:
          enum:
            - tool
          title: Type
          type: string
      required:
        - name
        - type
      title: Tool
      type: object
    ResponseToolUseBlock:
      properties:
        id:
          title: Id
          type: string
        input:
          title: Input
          type: object
        name:
          minLength: 1
          title: Name
          type: string
        type:
          default: tool_use
          enum:
            - tool_use
          title: Type
          type: string
      required:
        - id
        - input
        - name
        - type
      title: Tool use
      type: object
    Usage:
      properties:
        input_tokens:
          description: The number of input tokens which were used.
          minimum: 0
          title: Input Tokens
          type: integer
        output_tokens:
          description: The number of output tokens which were used.
          minimum: 0
          title: Output Tokens
          type: integer
      required:
        - input_tokens
        - output_tokens
      title: Usage
      type: object
    InputSchema:
      type: object
      properties:
        properties:
          anyOf:
            - type: object
          title: Properties
        required:
          anyOf:
            - items:
                type: string
              type: array
          title: Required
        type:
          enum:
            - object
          title: Type
          type: string
      required:
        - type
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)
    apiKey:
      type: apiKey
      in: header
      name: x-api-key
      description: >-
        Use the following format for authentication: [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建嵌入请求

> Creates an embedding vector representing the input text.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /embeddings:
    post:
      tags:
        - Embeddings
      summary: Create Embeddings
      description: Creates an embedding vector representing the input text.
      operationId: createEmbedding
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/EmbeddingsRequest'
      responses:
        '200':
          description: '200'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EmbeddingsResponse'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    EmbeddingsRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          example: Qwen/Qwen3-Embedding-8B
          default: Qwen/Qwen3-Embedding-8B
          enum:
            - Qwen/Qwen3-Embedding-8B
            - Qwen/Qwen3-Embedding-4B
            - Qwen/Qwen3-Embedding-0.6B
        input:
          description: >
            Input text to embed must be provided as a string or an array of
            tokens. To process multiple inputs in a single request, pass an
            array of strings or an array of token arrays. The input length must
            not exceed the model's maximum token limit and should not be an
            empty string.

            The maximum input tokens for each model are as follows:


            BAAI/bge-large-zh-v1.5, BAAI/bge-large-en-v1.5,
            netease-youdao/bce-embedding-base_v1: 512

            BAAI/bge-m3: 8192

            Qwen/Qwen3-Embedding-8B, Qwen/Qwen3-Embedding-4B,
            Qwen/Qwen3-Embedding-0.6B: 32768
          default: >-
            Silicon flow embedding online: fast, affordable, and high-quality
            embedding services. come try it out!
          oneOf:
            - type: string
              title: string
              description: >-
                The string that will be turned into an embedding. the item must
                not exceed the max models tokens limitation.
              default: >-
                Silicon flow embedding online: fast, affordable, and
                high-quality embedding services. come try it out!
              example: >-
                Silicon flow embedding online: fast, affordable, and
                high-quality embedding services. come try it out!
            - type: array
              title: array
              description: >
                The array of strings that will be turned into an embedding. The
                array length must not exceed the max size, and the item must not
                exceed the max models tokens limitation.

                Current, the maximum array size is 32 , At the same time every
                item must not exceed 512 tokens for current models.
              minItems: 1
              maxItems: 32
              items:
                type: string
                default: '[''LLM'', ''Embedding'', ''RAG'']'
                example: '[''LLM'', ''Embedding'', ''RAG'']'
        encoding_format:
          description: >
            "The format to return the embeddings in. Can be either `float` or
            [`base64`](https://pypi.org/project/pybase64/). "
          example: float
          default: float
          type: string
          enum:
            - float
            - base64
        dimensions:
          description: >
            The number of dimensions the resulting output embeddings should
            have. Only supported in `Qwen/Qwen3` series.  -
            Qwen/Qwen3-Embedding-8B: [64,128,256,512,768,1024,2048,4096] - 
            Qwen/Qwen3-Embedding-4B:[64,128,256,512,768,1024,2048] -
            Qwen/Qwen3-Embedding-0.6B: [64,128,256,512,768,1024]
          type: integer
          example: 1024
    EmbeddingsResponse:
      type: object
      required:
        - object
        - model
        - data
        - usage
      properties:
        object:
          type: string
          description: The object type, which is always "list".
          enum:
            - - list
        model:
          description: The name of the model used to generate the embedding.
          type: string
        data:
          type: array
          description: The list of embeddings generated by the model.
          items:
            type: object
            required:
              - index
              - object
              - embedding
            properties:
              object:
                type: string
                enum:
                  - embedding
              embedding:
                type: array
                items:
                  type: number
              index:
                type: integer
        usage:
          type: object
          description: The usage information for the request.
          properties:
            prompt_tokens:
              type: integer
              description: The number of tokens used by the prompt.
            completion_tokens:
              type: integer
              description: The number of tokens used by the completion.
            total_tokens:
              type: integer
              description: The total number of tokens used by the request.
          required:
            - prompt_tokens
            - total_tokens
            - completion_tokens
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建重排序请求

> Creates a rerank request.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /rerank:
    post:
      tags:
        - Rerank
      summary: Create Rerank
      description: Creates a rerank request.
      operationId: createRerank
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RerankRequest'
      responses:
        '200':
          description: '200'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RerankResponse'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    RerankRequest:
      type: object
      required:
        - model
        - query
        - documents
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          example: Qwen/Qwen3-Reranker-8B
          default: Qwen/Qwen3-Reranker-8B
          enum:
            - Qwen/Qwen3-Reranker-8B
            - Qwen/Qwen3-Reranker-4B
            - Qwen/Qwen3-Reranker-0.6B
        query:
          type: string
          description: Required. The search query.
          example: Apple
        documents:
          type: array
          minItems: 1
          items:
            type: string
          description: >-
            Currently, only string lists are supported. Document objects will be
            supported in the future.
          example:
            - apple
            - banana
            - fruit
            - vegetable
          default:
            - apple
            - banana
            - fruit
            - vegetable
        top_n:
          type: integer
          example: 4
          description: Number of most relevant documents or indices to return.
        return_documents:
          type: boolean
          description: >-
            If false, the response does not include document text; if true, it
            includes the input document text.
        max_chunks_per_doc:
          type: integer
          description: >-
            Maximum number of chunks generated from within a document. Long
            documents are divided into multiple chunks for calculation, and the
            highest score among the chunks is taken as the document's score.
            only BAAI/bge-reranker-v2-m3, netease-youdao/bce-reranker-base_v1
            support this field.
        overlap_tokens:
          type: integer
          maximum: 80
          description: >-
            Number of token overlaps between adjacent chunks when documents are
            chunked. only BAAI/bge-reranker-v2-m3,
            netease-youdao/bce-reranker-base_v1 support this field.
    RerankResponse:
      type: object
      required:
        - id
        - results
        - tokens
      properties:
        id:
          type: string
        results:
          type: array
          items:
            type: object
            properties:
              document:
                type: object
                properties:
                  text:
                    type: string
                description: Original document content.
              index:
                type: integer
                description: >-
                  The index value of the position in the input candidate doc
                  array.
              relevance_score:
                type: number
                description: Similarity score.
        tokens:
          type: object
          properties:
            input_tokens:
              type: integer
            output_tokens:
              type: integer
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建文本补全请求

> Query a language, code, or image model.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /completions:
    post:
      tags:
        - Completion
      summary: Create completion
      description: Query a language, code, or image model.
      operationId: completions
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CompletionRequest'
      responses:
        '200':
          description: '200'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CompletionResponse'
            text/event-stream:
              schema:
                $ref: '#/components/schemas/CompletionStream'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorData'
      deprecated: false
components:
  schemas:
    CompletionRequest:
      type: object
      required:
        - model
        - prompt
      properties:
        prompt:
          type: string
          description: A string providing context for the model to complete.
          example: <s>[INST] What is the capital of Germany? [/INST]
        model:
          type: string
          description: >
            The name of the model to query [See all of SiliconFlow's chat
            models](https://docs.siliconflow.com/api-reference/models/get-model-list)
          example: deepseek-ai/DeepSeek-R1
          default: deepseek-ai/DeepSeek-R1
          enum:
            - tencent/Hunyuan-MT-7B
            - Qwen/Qwen3-Next-80B-A3B-Thinking
            - Qwen/Qwen3-Next-80B-A3B-Instruct
            - inclusionAI/Ring-flash-2.0
            - inclusionAI/Ling-mini-2.0
            - inclusionAI/Ling-flash-2.0
            - ByteDance-Seed/Seed-OSS-36B-Instruct
            - google/gemma-4-26B-A4B-it
            - google/gemma-4-31B-it
            - openai/gpt-oss-120b
            - openai/gpt-oss-20b
            - MiniMaxAI/MiniMax-M2.5
            - MiniMaxAI/MiniMax-M2.1
            - Qwen/Qwen2.5-14B-Instruct
            - Qwen/Qwen2.5-32B-Instruct
            - Qwen/Qwen2.5-72B-Instruct
            - Qwen/Qwen2.5-72B-Instruct-128K
            - Qwen/Qwen2.5-7B-Instruct
            - Qwen/Qwen3-14B
            - Qwen/Qwen3-235B-A22B
            - Qwen/Qwen3-235B-A22B-Instruct-2507
            - Qwen/Qwen3-235B-A22B-Thinking-2507
            - Qwen/Qwen3-30B-A3B-Instruct-2507
            - Qwen/Qwen3-30B-A3B-Thinking-2507
            - Qwen/Qwen3-32B
            - Qwen/Qwen3-8B
            - Qwen/Qwen3-Coder-30B-A3B-Instruct
            - Qwen/Qwen3.5-122B-A10B
            - Qwen/Qwen3.5-27B
            - Qwen/Qwen3.5-35B-A3B
            - Qwen/Qwen3.5-397B-A17B
            - Qwen/Qwen3.5-9B
            - Qwen/Qwen3.6-27B
            - Qwen/Qwen3.6-35B-A3B
            - THUDM/GLM-4-32B-0414
            - THUDM/GLM-4-9B-0414
            - THUDM/GLM-Z1-32B-0414
            - THUDM/GLM-Z1-9B-0414
            - baidu/ERNIE-4.5-300B-A47B
            - deepseek-ai/DeepSeek-R1
            - deepseek-ai/DeepSeek-V3.2-Exp
            - deepseek-ai/DeepSeek-V3.2
            - deepseek-ai/DeepSeek-V3.1-Terminus
            - deepseek-ai/DeepSeek-V3.1
            - deepseek-ai/DeepSeek-V3
            - deepseek-ai/DeepSeek-V4-Flash
            - deepseek-ai/DeepSeek-V4-Pro
            - nex-agi/DeepSeek-V3.1-Nex-N1
            - meta-llama/Meta-Llama-3.1-8B-Instruct
            - moonshotai/Kimi-K2-Instruct-0905
            - moonshotai/Kimi-K2-Instruct
            - moonshotai/Kimi-K2-Thinking
            - moonshotai/Kimi-K2.6
            - tencent/Hunyuan-A13B-Instruct
            - tencent/Hy3-preview
            - zai-org/GLM-5.1
            - zai-org/GLM-5
            - zai-org/GLM-4.7
            - zai-org/GLM-4.6
            - zai-org/GLM-4.5
        max_tokens:
          type: integer
          description: The maximum number of tokens to generate.
        stop:
          type: array
          description: >-
            A list of string sequences that will truncate (stop) inference text
            output. For example, "</s>" will stop generation as soon as the
            model generates the given token.
          items:
            type: string
        temperature:
          type: number
          description: >-
            A decimal number from 0-1 that determines the degree of randomness
            in the response. A temperature less than 1 favors more correctness
            and is appropriate for question answering or summarization. A value
            closer to 1 introduces more randomness in the output.
          format: float
        top_p:
          type: number
          description: >-
            A percentage (also called the nucleus parameter) that's used to
            dynamically adjust the number of choices for each predicted token
            based on the cumulative probabilities. It specifies a probability
            threshold below which all less likely tokens are filtered out. This
            technique helps maintain diversity and generate more fluent and
            natural-sounding text.
          format: float
        top_k:
          type: integer
          description: >-
            An integer that's used to limit the number of choices for the next
            predicted word or token. It specifies the maximum number of tokens
            to consider at each step, based on their probability of occurrence.
            This technique helps to speed up the generation process and can
            improve the quality of the generated text by focusing on the most
            likely options.
          format: int32
        repetition_penalty:
          type: number
          description: >-
            A number that controls the diversity of generated text by reducing
            the likelihood of repeated sequences. Higher values decrease
            repetition.
          format: float
        stream:
          type: boolean
          description: >-
            If true, stream tokens as Server-Sent Events as the model generates
            them instead of waiting for the full model response. The stream
            terminates with `data: [DONE]`. If false, return a single JSON
            object containing the results.
        'n':
          type: integer
          description: The number of completions to generate for each prompt.
          minimum: 1
          maximum: 128
        presence_penalty:
          type: number
          description: >-
            A number between -2.0 and 2.0 where a positive value increases the
            likelihood of a model talking about new topics.
          format: float
        frequency_penalty:
          type: number
          description: >-
            A number between -2.0 and 2.0 where a positive value decreases the
            likelihood of repeating tokens that have already been mentioned.
          format: float
        logit_bias:
          type: object
          additionalProperties:
            type: number
            format: float
          description: >-
            Adjusts the likelihood of specific tokens appearing in the generated
            output.
          example:
            '105': 21.4
            '1024': -10.5
        seed:
          type: integer
          description: >-
            If specified, the system will make its best effort to perform
            deterministic sampling, so repeated requests with the same seed and
            parameters should return the same results. Determinism is not
            guaranteed to be implemented; the system_fingerprint response
            parameter should be referenced to monitor backend changes.
          example: 42
    CompletionResponse:
      type: object
      properties:
        id:
          type: string
        choices:
          $ref: '#/components/schemas/CompletionChoicesData'
        prompt:
          $ref: '#/components/schemas/PromptPart'
        usage:
          $ref: '#/components/schemas/UsageData'
        created:
          type: integer
        model:
          type: string
        object:
          type: string
          enum:
            - text_completion
      required:
        - id
        - choices
        - usage
        - created
        - model
        - object
    CompletionStream:
      oneOf:
        - $ref: '#/components/schemas/CompletionEvent'
    ErrorData:
      type: object
      required:
        - error
      properties:
        error:
          type: object
          properties:
            message:
              type: string
              nullable: false
            type:
              type: string
              nullable: false
            param:
              type: string
              nullable: true
              default: null
            code:
              type: string
              nullable: true
              default: null
          required:
            - type
            - message
            - param
            - code
    CompletionChoicesData:
      type: array
      items:
        type: object
        properties:
          text:
            type: string
          finish_reason:
            $ref: '#/components/schemas/FinishReason'
          logprobs:
            allOf:
              - $ref: '#/components/schemas/LogprobsPart'
              - nullable: true
    PromptPart:
      type: array
      items:
        type: object
        properties:
          text:
            type: string
            example: <s>[INST] What is the capital of France? [/INST]
            default: <s>[INST] What is the capital of France? [/INST]
          logprobs:
            $ref: '#/components/schemas/LogprobsPart'
    UsageData:
      type: object
      properties:
        prompt_tokens:
          type: integer
        completion_tokens:
          type: integer
        total_tokens:
          type: integer
    CompletionEvent:
      type: object
      required:
        - data
      properties:
        data:
          $ref: '#/components/schemas/CompletionChunk'
    FinishReason:
      type: string
      enum:
        - stop
        - eos
        - length
        - tool_calls
    LogprobsPart:
      type: object
      properties:
        tokens:
          type: array
          items:
            type: string
          description: List of token strings
        token_logprobs:
          type: array
          items:
            type: number
            format: float
          description: List of token log probabilities
    CompletionChunk:
      type: object
      required:
        - id
        - token
        - choices
        - usage
        - finish_reason
      properties:
        id:
          type: string
        token:
          $ref: '#/components/schemas/CompletionToken'
        choices:
          title: CompletionChoices
          type: array
          items:
            $ref: '#/components/schemas/CompletionChoice'
        tool_calls:
          type: array
          items:
            $ref: '#/components/schemas/ChatCompletionMessageToolCallChunk'
        usage:
          allOf:
            - $ref: '#/components/schemas/UsageData'
            - nullable: true
        finish_reason:
          allOf:
            - $ref: '#/components/schemas/FinishReason'
            - nullable: true
    CompletionToken:
      type: object
      required:
        - id
        - text
        - logprob
        - special
      properties:
        id:
          type: integer
        text:
          type: string
        logprob:
          type: number
          format: float
        special:
          type: boolean
    CompletionChoice:
      type: object
      required:
        - index
      properties:
        text:
          type: string
    ChatCompletionMessageToolCallChunk:
      type: object
      properties:
        index:
          type: integer
        id:
          type: string
          description: The ID of the tool call.
        type:
          type: string
          enum:
            - function
          description: The type of the tool. Currently, only `function` is supported.
        function:
          type: object
          properties:
            name:
              type: string
              description: The name of the function to call.
            arguments:
              type: string
              description: >-
                The arguments to call the function with, as generated by the
                model in JSON format. Note that the model does not always
                generate valid JSON, and may hallucinate parameters not defined
                by your function schema. Validate the arguments in your code
                before calling your function.
      required:
        - index
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建图片生成请求

> Creates an image response for the given prompt. The URL for the generated image is valid for one hour. Please make sure to download and store it promptly to avoid any issues due to URL expiration.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /images/generations:
    post:
      tags:
        - Image
      summary: Image Generation
      description: >-
        Creates an image response for the given prompt. The URL for the
        generated image is valid for one hour. Please make sure to download and
        store it promptly to avoid any issues due to URL expiration.
      operationId: ImageGeneration
      requestBody:
        content:
          application/json:
            schema:
              oneOf:
                - $ref: '#/components/schemas/FLUX.2-pro'
                - $ref: '#/components/schemas/FLUX.2-flex'
                - $ref: '#/components/schemas/Qwen-Image'
                - $ref: '#/components/schemas/Z-Image'
                - $ref: '#/components/schemas/FLUX.1-Kontext'
                - $ref: '#/components/schemas/FLUX.1-Kontext-dev'
                - $ref: '#/components/schemas/FLUX-1.1-pro'
                - $ref: '#/components/schemas/FLUX-1.1-pro-Ultra'
                - $ref: '#/components/schemas/FLUX.1-schnell'
                - $ref: '#/components/schemas/FLUX.1-dev'
      responses:
        '200':
          description: '200'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ImagesGenerationResponse'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    FLUX.2-pro:
      title: FLUX.2-pro
      type: object
      required:
        - model
        - prompt
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX.2-pro
          enum:
            - black-forest-labs/FLUX.2-pro
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          example: A serene landscape with mountains and a lake at sunset
          description: The text prompt describing the image to generate.
        image_size:
          type: string
          title: Image size, format is [width]x[height]
          description: |
            Image resolution in "widthxheight" format. Supported resolutions:
              - "512x512" (1:1)
              - "768x1024" (3:4)
              - "1024x768" (4:3)
              - "576x1024" (9:16)
              - "1024x576" (16:9)
          enum:
            - 512x512
            - 768x1024
            - 1024x768
            - 576x1024
            - 1024x576
          default: 512x512
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
          description: >-
            Random seed for reproducible generation. If not specified, a random
            seed will be used.
        output_format:
          description: Output format for the generated image.
          default: png
          type: string
          enum:
            - png
            - jpeg
    FLUX.2-flex:
      title: FLUX.2-flex
      type: object
      required:
        - model
        - prompt
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX.2-flex
          enum:
            - black-forest-labs/FLUX.2-flex
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          example: A futuristic cityscape with flying cars and neon lights
          description: The text prompt describing the image to generate.
        image_size:
          type: string
          title: Image size, format is [width]x[height]
          description: |
            Image resolution in "widthxheight" format. Supported resolutions:
              - "512x512" (1:1)
              - "768x1024" (3:4)
              - "1024x768" (4:3)
              - "576x1024" (9:16)
              - "1024x576" (16:9)
          enum:
            - 512x512
            - 768x1024
            - 1024x768
            - 576x1024
            - 1024x576
          default: 512x512
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
          description: >-
            Random seed for reproducible generation. If not specified, a random
            seed will be used.
        cfg:
          title: CFG Scale
          type: number
          description: >-
            CFG (Classifier-Free Guidance) is a technique that adjusts how
            closely generated outputs follow input prompts by balancing
            precision and creativity. This field is only applicable to
            Qwen/Qwen-Image models.For text generation scenarios, the CFG value
            must be greater than 1. The official configuration uses 50 steps
            with CFG 4.0. When CFG is set too small, it becomes nearly
            impossible to generate text.
          minimum: 0.1
          maximum: 20
        num_inference_steps:
          title: Number of Inference Steps
          type: integer
          minimum: 1
          maximum: 50
          default: 25
          description: >-
            Number of denoising steps. More steps generally produce higher
            quality images but take longer.
        output_format:
          description: Output format for the generated image.
          default: png
          type: string
          enum:
            - png
            - jpeg
    Qwen-Image:
      title: Qwen-Image
      type: object
      required:
        - model
        - prompt
      properties:
        model:
          type: string
          enum:
            - Qwen/Qwen-Image
            - Qwen/Qwen-Image-Edit
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          example: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        negative_prompt:
          title: Negative Prompt
          type: string
          description: negative prompt
        image_size:
          type: string
          title: Image size, format is  [width]x[height].
          description: >
            Image resolution in "widthxheight" format (Required). To ensure
            optimal quality, using the recommended values for your model is
            strongly advised.
              Recommended Values:  
                - "1328x1328" (1:1)
                - "1664x928" (16:9)
                - "928x1664" (9:16)
                - "1472x1140" (4:3)
                - "1140x1472" (3:4)
                - "1584x1056" (3:2)
                - "1056x1584" (2:3)
        batch_size:
          title: Number Images
          description: number of output images
          type: integer
          minimum: 1
          maximum: 4
          default: 1
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
        num_inference_steps:
          title: Number Inference Steps
          description: number of inference steps
          type: integer
          minimum: 1
          maximum: 100
          default: 20
        guidance_scale:
          title: Guidance Scale
          description: >-
            This value is used to control the degree of match between the
            generated image and the given prompt. The higher the value, the more
            the generated image will tend to strictly match the text prompt. The
            lower the value, the more creative and diverse the generated image
            will be, potentially containing more unexpected elements.
          type: number
          minimum: 0
          maximum: 20
          default: 7.5
        cfg:
          title: CFG Scale
          type: number
          description: >-
            CFG (Classifier-Free Guidance) is a technique that adjusts how
            closely generated outputs follow input prompts by balancing
            precision and creativity. This field is only applicable to
            Qwen/Qwen-Image models.For text generation scenarios, the CFG value
            must be greater than 1. The official configuration uses 50 steps
            with CFG 4.0. When CFG is set too small, it becomes nearly
            impossible to generate text.
          minimum: 0.1
          maximum: 20
        image:
          $ref: '#/components/schemas/upload_image'
    Z-Image:
      title: Z-Image
      type: object
      required:
        - model
        - prompt
      properties:
        model:
          type: string
          enum:
            - Tongyi-MAI/Z-Image-Turbo
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          example: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        negative_prompt:
          title: Negative Prompt
          type: string
          description: negative prompt
        image_size:
          type: string
          title: Image size, format is  [width]x[height].
          description: >
            Image resolution in "widthxheight" format (Required). To ensure
            optimal quality, using the recommended values for your model is
            strongly advised.
              Recommended Values:  
                - "512x512" (1:1)
                - "768x1024" (3:4)
                - "1024x576" (16:9)
                - "576x1024" (9:16)
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
    FLUX.1-Kontext:
      title: FLUX.1-Kontext
      type: object
      required:
        - model
        - prompt
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX.1-Kontext-max
          enum:
            - black-forest-labs/FLUX.1-Kontext-max
            - black-forest-labs/FLUX.1-Kontext-pro
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          example: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        input_image:
          $ref: '#/components/schemas/upload_image'
          description: The image parameter is a required field.
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
        aspect_ratio:
          type: string
          description: Aspect ratio of the image between 21:9 and 9:21
          example: '21:9'
        output_format:
          description: Output format for the generated image. Can be 'jpeg' or 'png'.
          default: png
          type: string
          enum:
            - png
            - jpeg
        prompt_upsampling:
          description: >-
            Whether to perform upsampling on the prompt. If active,
            automatically modifies the prompt for more creative generation.
          type: boolean
          example: false
          default: false
        safety_tolerance:
          description: >-
            Tolerance level for input and output moderation. Between 0 and 6, 0
            being most strict, 6 being least strict. Limit of 2 for Image to
            Image.
          type: integer
          minimum: 0
          maximum: 6
          example: 2
    FLUX.1-Kontext-dev:
      title: FLUX.1-Kontext-dev
      type: object
      required:
        - model
        - prompt
        - image
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX.1-Kontext-dev
          enum:
            - black-forest-labs/FLUX.1-Kontext-dev
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          default: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
        prompt_enhancement:
          type: boolean
          description: >-
            Prompt enhancement switch, When enabled, the prompt is optimized to
            be detailed and model-friendly.
          example: false
          default: false
        image:
          $ref: '#/components/schemas/upload_image'
          description: The image parameter is a required field.
    FLUX-1.1-pro:
      title: FLUX-1.1-pro
      type: object
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX-1.1-pro
          enum:
            - black-forest-labs/FLUX-1.1-pro
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          example: ein fantastisches bild
        image_prompt:
          type: string
          description: Optional base64 encoded image to use as a prompt for generation.
        width:
          type: integer
          description: Width of the generated image in pixels. It must be a multiple of 32.
          minimum: 256
          maximum: 1440
          default: 1024
        height:
          type: integer
          description: Width of the generated image in pixels. It must be a multiple of 32.
          minimum: 256
          maximum: 1440
          default: 768
        prompt_upsampling:
          type: boolean
          default: false
          description: >-
            Whether to upsample the prompt. If enabled, the prompt will be
            automatically adjusted to encourage more creative generation.
        seed:
          type: integer
          minimum: 0
          maximum: 9999999999
        safety_tolerance:
          type: integer
          description: >-
            Tolerance level for input and output review. Ranges from 0 to 6,
            where 0 is the strictest and 6 is the most lenient.
          minimum: 0
          maximum: 6
          default: 2
        output_format:
          type: string
          description: >-
            Output format for the generated image. It can be either 'jpeg' or
            'png'.
          enum:
            - jpeg
            - png
    FLUX-1.1-pro-Ultra:
      title: FLUX-1.1-pro-Ultra
      type: object
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX-1.1-pro-Ultra
          enum:
            - black-forest-labs/FLUX-1.1-pro-Ultra
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          default: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        negative_prompt:
          title: Negative Prompt
          type: string
          description: negative prompt
        image_size:
          title: Image size, format is  [width]x[height].
          enum:
            - 1024x1024
            - 960x1280
            - 768x1024
            - 720x1440
            - 720x1280
            - others
          default: 1024x1024
        batch_size:
          title: Number Images
          description: number of output images
          type: integer
          minimum: 1
          maximum: 4
          default: 1
        seed:
          type: integer
          minimum: 0
          maximum: 9999999999
        aspect_ratio:
          type: string
          description: Aspect ratio of the image between 21:9 and 9:21
          example: '21:9'
        safety_tolerance:
          type: integer
          description: >-
            Tolerance level for input and output review. Ranges from 0 to 6,
            where 0 is the strictest and 6 is the most lenient.
          minimum: 0
          maximum: 6
          default: 2
        output_format:
          type: string
          description: >-
            Output format for the generated image. It can be either 'jpeg' or
            'png'.
          enum:
            - jpeg
            - png
        raw:
          type: boolean
          default: false
          description: Generate less processed, more natural-looking images
        image_prompt:
          type: string
          description: Optional image to remix in base64 format
        image_prompt_strength:
          type: integer
          description: Blend between the prompt and the image prompt
          minimum: 0
          maximum: 1
          default: 0.1
    FLUX.1-schnell:
      title: FLUX.1-schnell
      type: object
      required:
        - model
        - prompt
        - image_size
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX.1-schnell
          enum:
            - black-forest-labs/FLUX.1-schnell
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          default: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        image_size:
          title: Image Size
          description: image size, format is [width]x[height]
          enum:
            - 1024x1024
            - 512x1024
            - 768x512
            - 768x1024
            - 1024x576
            - 576x1024
          default: 1024x1024
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
        prompt_enhancement:
          type: boolean
          description: >-
            Prompt enhancement switch, When enabled, the prompt is optimized to
            be detailed and model-friendly.
          example: false
          default: false
    FLUX.1-dev:
      title: FLUX.1-dev
      type: object
      required:
        - model
        - prompt
        - image_size
        - num_inference_steps
      properties:
        model:
          type: string
          default: black-forest-labs/FLUX.1-dev
          enum:
            - black-forest-labs/FLUX.1-dev
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        prompt:
          type: string
          default: >-
            an island near sea, with seagulls, moon shining over the sea, light
            house, boats int he background, fish flying over the sea
        image_size:
          title: >-
            Image size, format is  [width]x[height], with a maximum of 2359296
            pixels.
          enum:
            - 1024x1024
            - 960x1280
            - 768x1024
            - 720x1440
            - 720x1280
            - others
          default: 1024x1024
        seed:
          title: Seed
          type: integer
          minimum: 0
          maximum: 9999999999
        num_inference_steps:
          title: Number Inference Steps
          description: inference steps
          type: integer
          minimum: 1
          maximum: 30
          default: 20
        prompt_enhancement:
          type: boolean
          description: >-
            Prompt enhancement switch, When enabled, the prompt is optimized to
            be detailed and model-friendly.
          example: false
          default: false
    ImagesGenerationResponse:
      type: object
      properties:
        images:
          type: array
          items:
            type: object
            properties:
              url:
                description: >-
                  The URL for the generated image is valid for one hour. Please
                  make sure to download and store it promptly to avoid any
                  issues due to URL expiration.
                type: string
        timings:
          type: object
          properties:
            inference:
              type: number
              format: float
        seed:
          type: integer
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
    upload_image:
      title: Upload Image
      description: >-
        The image that needs to be uploaded should be converted into base64
        format like "data:image/png;base64, XXX"
      type: string
      example: data:image/png;base64, XXX
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 上传参考音频

> Upload user-provided voice style, which can be in base64 encoding or file format. Refer to (https://docs.siliconflow.com/capabilities/text-to-speech#2-2)

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /uploads/audio/voice:
    post:
      summary: Upload Voice
      description: >-
        Upload user-provided voice style, which can be in base64 encoding or
        file format. Refer to
        (https://docs.siliconflow.com/capabilities/text-to-speech#2-2)
      operationId: uploadAudioVoice
      parameters: []
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                model:
                  type: string
                  example: FunAudioLLM/CosyVoice2-0.5B
                  enum:
                    - FunAudioLLM/CosyVoice2-0.5B
                  description: Predefined voice style model name
                customName:
                  type: string
                  example: your-voice-name
                  description: User-defined voice style name
                  default: Silicon flow voice style model
                text:
                  type: string
                  example: >-
                    In the midst of ignorance, a day in the dream comes to an
                    end, and a new cycle begins.
                  description: Corresponding text content for the audio
                  default: >-
                    In the midst of ignorance, a day in the dream comes to an
                    end, and a new cycle begins.
              required:
                - model
                - customName
                - text
              oneOf:
                - properties:
                    audio:
                      title: Base64 encoding of audio
                      type: string
                      example: data:audio/mpeg;base64,aGVsbG93b3JsZA==
                      description: >-
                        Audio file encoded in base64 with the header format of
                        `data:audio/mpeg;base64`
                - properties:
                    file:
                      title: File upload for audio
                      type: string
                      format: binary
                      example: /path/to/audio.mp3
                      description: File to upload
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  uri:
                    type: string
                    example: speech:your-voice-name:xxx:xxx
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
                type: object
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建文本转语音请求

> Generate audio from input text. The data generated by the interface is the binary data of the audio, which requires the user to handle it themselves. Reference:https://docs.siliconflow.com/capabilities/text-to-speech#5

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /audio/speech:
    post:
      tags:
        - Audio
      summary: Create Speech
      description: >-
        Generate audio from input text. The data generated by the interface is
        the binary data of the audio, which requires the user to handle it
        themselves.
        Reference:https://docs.siliconflow.com/capabilities/text-to-speech#5
      operationId: createSpeech
      requestBody:
        required: true
        content:
          application/json:
            schema:
              oneOf:
                - $ref: '#/components/schemas/fish-speech-1.5'
                - $ref: '#/components/schemas/CosyVoice2-0.5B'
      responses:
        '200':
          description: >-
            Generate audio based on the input text. The data generated by the
            interface is in binary format and requires the user to process it
            themselves.
            Reference:https://docs.siliconflow.com/capabilities/text-to-speech#5
          headers:
            Transfer-Encoding:
              schema:
                type: string
              description: chunked
          content:
            application/audio:
              schema:
                type: string
                format: binary
                example: Audio binary data
            audio/wav:
              schema:
                type: string
                format: binary
                example: Audio binary data
            audio/opus:
              schema:
                type: string
                format: binary
                example: Audio binary data
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
                type: object
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
components:
  schemas:
    fish-speech-1.5:
      title: fish-speech-1.5
      type: object
      required:
        - model
        - input
        - voice
      additionalProperties: false
      properties:
        model:
          type: string
          enum:
            - fishaudio/fish-speech-1.5
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        input:
          type: string
          description: The text to generate audio for.
          example: The text to generate audio for
          maxLength: 128000
          minLength: 1
        voice:
          type: string
          enum:
            - fishaudio/fish-speech-1.5:alex
            - fishaudio/fish-speech-1.5:anna
            - fishaudio/fish-speech-1.5:bella
            - fishaudio/fish-speech-1.5:benjamin
            - fishaudio/fish-speech-1.5:charles
            - fishaudio/fish-speech-1.5:claire
            - fishaudio/fish-speech-1.5:david
            - fishaudio/fish-speech-1.5:diana
        response_format:
          description: >-
            The format to audio out. Supported formats are `mp3`, `opus`, `wav`,
            `pcm`
          default: mp3
          type: string
          enum:
            - mp3
            - opus
            - wav
            - pcm
        sample_rate:
          description: >-
            Control the output sample rate. The default values and differ for
            different video output types, as follows: opus: Supports 48000 Hz.
            wav, pcm: Supports 8000, 16000, 24000, 32000, 44100 Hz, with a
            default of 44100 Hz. mp3: Supports 32000, 44100 Hz, with a default
            of 44100 Hz.
          type: number
          example: 32000
          enum:
            - 8000
            - 16000
            - 24000
            - 32000
            - 44100
            - 48000
        stream:
          description: streaming or not
          type: boolean
          default: true
        speed:
          type: number
          description: >-
            The speed of the generated audio. Select a value from `0.25` to
            `4.0`. `1.0` is the default.
          format: float
          minimum: 0.25
          maximum: 4
          default: 1
        gain:
          type: number
          format: float
          minimum: -10
          maximum: 10
          default: 0
    CosyVoice2-0.5B:
      title: CosyVoice2-0.5B
      type: object
      required:
        - model
        - input
      additionalProperties: false
      properties:
        model:
          type: string
          enum:
            - FunAudioLLM/CosyVoice2-0.5B
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
        input:
          type: string
          description: >-
            For natural language instructions, add a special end marker
            "<|endofprompt|>" before the natural language description. These
            descriptions cover aspects such as emotion, speaking speed,
            role-playing, and dialects. For detailed instructions, insert pitch
            bursts between text markers, using markers like "[laughter]" and
            "[breath]." Additionally, we apply pitch feature markers to phrases;
            for example:Can you say it with a happy emotion? <|endofprompt|>
            Today is really happy, Spring Festival is coming! I’m so happy,
            Spring Festival is coming! [laughter] [breath].
          example: >-
            Can you say it with a happy emotion? <|endofprompt|>I'm so happy,
            Spring Festival is coming!
          default: >-
            Can you say it with a happy emotion? <|endofprompt|>I'm so happy,
            Spring Festival is coming!
          maxLength: 128000
          minLength: 1
        voice:
          type: string
          enum:
            - FunAudioLLM/CosyVoice2-0.5B:alex
            - FunAudioLLM/CosyVoice2-0.5B:anna
            - FunAudioLLM/CosyVoice2-0.5B:bella
            - FunAudioLLM/CosyVoice2-0.5B:benjamin
            - FunAudioLLM/CosyVoice2-0.5B:charles
            - FunAudioLLM/CosyVoice2-0.5B:claire
            - FunAudioLLM/CosyVoice2-0.5B:david
            - FunAudioLLM/CosyVoice2-0.5B:diana
        references:
          description: The voice field and references field are mutually exclusive.
          type: array
          items:
            type: object
            properties:
              audio:
                oneOf:
                  - type: string
                    format: uri
                    description: >-
                      A URL pointing to an audio file (e.g.,
                      `https://example.com/audio.mp3`).
                  - type: string
                    pattern: ^data:audio\/\w+;base64,[A-Za-z0-9+/=]+$
                    description: >-
                      A base64-encoded audio string (e.g.,
                      `data:audio/mp3;base64,ABC123...`).
              text:
                description: >-
                  The audio content, which can be either a URL pointing to an
                  audio file or a base64-encoded audio string.
                type: string
        response_format:
          description: >-
            The format to audio out. Supported formats are `mp3`, `opus`, `wav`,
            `pcm`
          default: mp3
          type: string
          enum:
            - mp3
            - opus
            - wav
            - pcm
        sample_rate:
          description: >-
            Control the output sample rate. The default values and differ for
            different video output types, as follows: opus: Supports 48000 Hz.
            wav, pcm: Supports 8000, 16000, 24000, 32000, 44100 Hz, with a
            default of 44100 Hz. mp3: Supports 32000, 44100 Hz, with a default
            of 44100 Hz.
          type: number
          default: 32000
        stream:
          description: streaming or not
          type: boolean
        speed:
          type: number
          description: >-
            The speed of the generated audio. Select a value from `0.25` to
            `4.0`. `1.0` is the default.
          format: float
          minimum: 0.25
          maximum: 4
          default: 1
        gain:
          type: number
          format: float
          minimum: -10
          maximum: 10
          default: 0
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 参考音频列表获取

> Get list of user-defined voice styles

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /audio/voice/list:
    get:
      tags:
        - Audio
      summary: Get Voice List
      description: Get list of user-defined voice styles
      operationId: audioVoiceList
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                description: User-defined voice style list response
                properties:
                  results:
                    type: array
                    description: Predefined voice style list
                    items:
                      type: object
                      properties:
                        model:
                          type: string
                          example: fishaudio/fish-speech-1.4
                          description: Predefined voice style model name
                        customName:
                          type: string
                          example: your-voice-name
                          description: User-defined voice style name
                        text:
                          type: string
                          example: >-
                            In the midst of ignorance, a day in the dream comes
                            to an end, and a new cycle begins.
                          description: Corresponding text content for the audio
                        uri:
                          type: string
                          example: speech:your-voice-name:xxx:xxx
                          description: URI generated after uploading the audio
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
                type: object
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
components:
  schemas:
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 删除参考音频

> Delete user-defined voice style

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /audio/voice/deletions:
    post:
      tags:
        - Audio
      summary: Delete User Voice
      description: Delete user-defined voice style
      operationId: AudioVoiceDeletions
      parameters: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                uri:
                  type: string
                  example: speech:your-voice-name:xxx:xxxx
                  description: Voice style to be deleted by the user
              required:
                - uri
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: string
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
                type: object
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 创建视频生成请求

> Generate a video through the input prompt. This API returns the user's current request ID. The user needs to poll the status interface to get the specific video link. The generated result is valid for 10 minutes, so please retrieve the video link promptly.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /video/submit:
    post:
      tags:
        - Video
      summary: Submit video
      description: >-
        Generate a video through the input prompt. This API returns the user's
        current request ID. The user needs to poll the status interface to get
        the specific video link. The generated result is valid for 10 minutes,
        so please retrieve the video link promptly.
      requestBody:
        content:
          application/json:
            schema:
              oneOf:
                - $ref: '#/components/schemas/Wan2.2-T2V-A14B'
                - $ref: '#/components/schemas/Wan2.2-I2V-A14B'
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  requestId:
                    type: string
                    description: >-
                      The requestId generated by this request needs to be used
                      when calling the status interface.
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
                type: object
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/RateLimitData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
components:
  schemas:
    Wan2.2-T2V-A14B:
      title: Wan-AI Text-to-Video
      type: object
      required:
        - model
        - prompt
        - image_size
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          enum:
            - Wan-AI/Wan2.2-T2V-A14B
            - Wan-AI/Wan2.1-T2V-14B-720P
            - Wan-AI/Wan2.1-T2V-14B-720P-Turbo
        prompt:
          type: string
          description: The text prompt to generate the video description from.
        negative_prompt:
          type: string
          description: negative prompt
        image_size:
          type: string
          description: Length-width ratio of the generated image.
          enum:
            - 1280x720
            - 720x1280
            - 960x960
        seed:
          type: integer
          description: The seed for the random number generator.
    Wan2.2-I2V-A14B:
      title: Wan-AI Image-to-Video
      type: object
      required:
        - model
        - prompt
        - image_size
        - image
      properties:
        model:
          type: string
          description: >-
            Corresponding Model Name. To better enhance service quality, we will
            make periodic changes to the models provided by this service,
            including but not limited to model on/offlining and adjustments to
            model service capabilities. We will notify you of such changes
            through appropriate means such as announcements or message pushes
            where feasible.
          enum:
            - Wan-AI/Wan2.2-I2V-A14B
            - Wan-AI/Wan2.1-I2V-14B-720P
            - Wan-AI/Wan2.1-I2V-14B-720P-Turbo
        prompt:
          type: string
          description: The text prompt to generate the video description from.
        negative_prompt:
          type: string
          description: negative prompt
        image_size:
          type: string
          description: Length-width ratio of the generated image.
          enum:
            - 1280x720
            - 720x1280
            - 960x960
        image:
          description: >-
            The image that needs to be uploaded should be converted into base64
            format like "data:image/png;base64, XXX"
          type: string
          example: data:image/png;base64, XXX
        seed:
          type: integer
          description: The seed for the random number generator.
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    RateLimitData:
      type: object
      required:
        - message
        - data
      properties:
        message:
          type: string
          example: >-
            Request was rejected due to rate limiting. If you want more, please
            contact contact@siliconflow.com. Details:TPM limit reached.
        data:
          type: string
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 获取视频生成链接请求

> Get the user-generated video. The URL for the generated video is valid for one hour. Please make sure to download and store it promptly to avoid any issues due to URL expiration.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /video/status:
    post:
      tags:
        - video
      summary: get video
      description: >-
        Get the user-generated video. The URL for the generated video is valid
        for one hour. Please make sure to download and store it promptly to
        avoid any issues due to URL expiration.
      requestBody:
        content:
          application/json:
            schema:
              oneOf:
                - $ref: '#/components/schemas/getVideosRequest'
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/getVideosResponse'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BadRquestData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UnauthorizedData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/NotFoundData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OverloadedtData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TimeoutData'
      deprecated: false
components:
  schemas:
    getVideosRequest:
      type: object
      required:
        - requestId
      properties:
        requestId:
          type: string
          description: The requestId returned by the interface submit.
    getVideosResponse:
      type: object
      properties:
        status:
          type: string
          description: >-
            Status of the operation. Possible values are
            'Succeed','InQueue','InProgress','Failed'.
          enum:
            - Succeed
            - InQueue
            - InProgress
            - Failed
        reason:
          type: string
          description: Reason for the operation
        results:
          type: object
          properties:
            videos:
              type: array
              items:
                type: object
                properties:
                  url:
                    description: >-
                      The URL for the generated image is valid for one hour.
                      Please make sure to download and store it promptly to
                      avoid any issues due to URL expiration.
                    type: string
            timings:
              type: object
              properties:
                inference:
                  type: number
                  format: double
                  description: Inference time
            seed:
              type: integer
              description: Seed value
    BadRquestData:
      type: object
      required:
        - message
        - data
        - code
      properties:
        code:
          type: integer
          nullable: true
          default: false
          example: 20012
        message:
          type: string
          nullable: false
        data:
          type: string
          nullable: false
    UnauthorizedData:
      type: string
      default: false
      example: Invalid token
    NotFoundData:
      type: string
      default: false
      example: 404 page not found
    OverloadedtData:
      type: object
      required:
        - code
        - message
        - data
      properties:
        code:
          type: integer
          example: 50505
        message:
          type: string
          example: Model service overloaded. Please try again later.
        data:
          type: string
          nullable: false
    TimeoutData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 获取用户模型列表

> Retrieve models information.

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /models:
    get:
      tags:
        - Models
      summary: Get Model List
      description: Retrieve models information.
      operationId: Retrieve a list of models.
      parameters:
        - name: type
          in: query
          description: The type of models
          required: false
          schema:
            type: string
            enum:
              - text
              - image
              - audio
              - video
        - name: sub_type
          in: query
          description: >-
            The sub type of models. You can use it to filter models individually
            without setting type.
          required: false
          schema:
            type: string
            enum:
              - chat
              - embedding
              - reranker
              - text-to-image
              - image-to-image
              - speech-to-text
              - text-to-video
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  object:
                    type: string
                    example: list
                  data:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                          example: stabilityai/stable-diffusion-xl-base-1.0
                        object:
                          type: string
                          example: model
                        created:
                          type: integer
                          example: 0
                        owned_by:
                          type: string
                          example: ''
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
      deprecated: false
components:
  schemas:
    StringData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````



> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.siliconflow.com/llms.txt
> Use this file to discover all available pages before exploring further.

# 获取用户账户信息

> Get user information including balance and status

## OpenAPI

````yaml
openapi: 3.0.0
info:
  title: SiliconFlow API
  description: The SiliconFlow REST API
  version: 1.0.0
  contact:
    name: SiliconFlow Support
    url: https://www.siliconflow.com/
  license:
    name: MIT
    url: https://github.com/siliconflow-inc/siliconflow-api/blob/main/LICENSE
servers:
  - url: https://api.siliconflow.com/v1
security:
  - bearerAuth: []
paths:
  /user/info:
    get:
      tags:
        - UserInfo
      summary: Get user information
      description: Get user information including balance and status
      operationId: user-info
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    example: 20000
                  message:
                    type: string
                    example: OK
                  status:
                    type: boolean
                    example: true
                  data:
                    type: object
                    properties:
                      id:
                        type: string
                        example: userid
                      name:
                        type: string
                        example: username
                        description: >-
                          This field will no longer be returned after June 11th,
                          and a fixed empty string will be output instead.
                      image:
                        type: string
                        example: user_avatar_image_url
                        description: >-
                          This field will no longer be returned after June 11th,
                          and a fixed empty string will be output instead.
                      email:
                        type: string
                        example: user_email_address
                        description: >-
                          This field will no longer be returned after June 11th,
                          and a fixed empty string will be output instead.
                      isAdmin:
                        type: boolean
                        example: false
                      balance:
                        type: string
                        example: '0.88'
                      status:
                        type: string
                        example: normal
                      introduction:
                        type: string
                        example: ''
                      role:
                        type: string
                        example: ''
                      chargeBalance:
                        type: string
                        example: '88.00'
                      totalBalance:
                        type: string
                        example: '88.88'
        '400':
          description: BadRequest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '401':
          description: Unauthorized
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '404':
          description: NotFound
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '429':
          description: RateLimit
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '503':
          description: Overloaded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
        '504':
          description: Timeout
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StringData'
      deprecated: false
components:
  schemas:
    StringData:
      type: string
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: your api key
      description: >-
        Use the following format for authentication: Bearer [<your api
        key>](https://cloud.siliconflow.com/account/ak)

````
