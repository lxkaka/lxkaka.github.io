# crewAI 搭建 AI agent 的原理及应用

单独使用语言模型（LLM）对于简单的任务比如让模型写一段文案来说是可以的，但更复杂的任务往往只依靠 LLM 很难取得良好的效果甚至不可用。
所以 AI agent 的提出就是为了弥补当前 LLM 在很多方面的能力不足。可以这么理解 LLM 就像人的大脑，可以理解人类的语言，agent 就好比给 LLM 装上了五官和四肢。

### AI agent
AI 代理（AI agent）是指使用 AI 技术设计和编程的一种计算机程序，其可以独立地进行某些任务并对环境做出反应。AI 代理可以被视为一个智能体，它能够感知其环境，通过自己的决策和行动来改变环境，并通过学习和适应来提高其性能。这种智能体同时使用短期记忆（上下文学习）和长期记忆（从外部向量存储中检索信息），有能力通过逐步“思考”来计划、将目标分解为更小的任务，并反思自己的表现。AI 代理通常包含多种技术，如机器学习、自然语言处理、计算机视觉、规划和推理等，这些技术使代理能够自主地处理信息并作出决策。

[LangChain](https://python.langchain.com/docs/modules/agents/)中已经实现了我们想要的部分 agent 功能。agent 会自己分析问题，选择合适的工具，最终解决问题。其中应用很广泛的一类就是 [ReAct](https://react-lm.github.io/)。

#### ReAct 
>ReAct 是 Reasoning and Acting（也有一说是 Reason Act）缩写，意思是 LLM 可以根据逻辑推理（Reason），构建完整系列行动（Act），从而达成期望目标。LLM 灵感来源是人类行为和推理之间的协同关系。人类根据这种协同关系学习新知识，做出决策，然后执行。LLM 在逻辑推理上有着非常优秀的表现，因此有理由相信 LLM 也可以像人类一样进行逻辑推理，学习知识，做出决策，并执行。在实际使用中，LLM 会发生幻觉和错误判断的情况。这是因为 LLM 在训练的时候接触到的知识有限。因此对超出训练过程中使用的数据进行逻辑分析时，LLM 就会开始不懂装懂地编造一些理由。因此对于解决这个问题最好的办法是，可以保证 LLM 在做出分析决策时，必须将应该有的知识提供给 LLM。

>ReAct 方式的作用就是协调 LLM 和外部的信息获取，与其他功能交互。如果说 LLM 是大脑，那 ReAct 框架就是这个大脑的手脚和五官。同时具备帮助 LLM 模型获取信息、输出内容与执行决策的能力。对于一个指定的任务目标，ReAct 框架会自动补齐 LLM 应该具备的知识和相关信息，然后再让 LLM 做出决策，并执行 LLM 的决策。

一个 ReAct 流程里，关键是三个概念：

Thought：由 LLM 生成，是 LLM 产生行为和依据。可以根据 LLM 的思考，来衡量他要采取的行为是否合理。这是一个可用来判断本次决策是否合理的关键依据。相较于人类，thought 的存在可以让 LLM 的决策变得更加有可解释性和可信度。

Act：Act 是指 LLM 判断本次需要执行的具体行为。Act 一般由两部分组成：行为和对象。用编程的说法就是 API 名称和对应的入参。LLM 模型最大的优势是，可以根据 Thought 的判断，选择需要使用的 API 并生成需要填入 API 的参数。从而保证了 ReAct 框架在执行层面的可行性。

Obs：LLM 框架对于外界输入的获取。它就像 LLM 的 五官，将外界的反馈信息同步给 LLM，协助 LLM 进一步的做分析或者决策。

一个完整的 ReAct 的行为，包涵以下几个流程：

1.输入目标：任务的起点。可以是用户的手动输入，也可以是依靠触发器（比如系统故障报警）。

2.LOOP：LLM 模型开始分析问题需要的步骤（Thought），按步骤执行 Act，根据观察到的信息（Obs），循环执行这个过程。直到判断任务目标达成。

3.Finish：任务最终执行成功，返回最终结果。

### crewAI
CrewAI 是一个基于角色扮演的 AI agent 团队自动化协作框架，它旨在为 AI agent 提供自动化设置，以促进 AI agent 之间的合作，使这些代理能够共同解决复杂问题。CrewAI 的主要构建模块包括代理、任务、工具和团队。

在 CrewAI 中，agent 是一个被编程为执行任务、做出决策并与其他代理进行通信的自治单元。将 agent 视为团队的成员，具有特定的技能和特定的工作要做。agent 可以担任不同的角色，例如“研究员”、“作家”或“客户支持”，每个角色都有助于团队的总体目标。agent 的关键属性包括角色、目标、背景故事和工具集。
任务是 CrewAI 中的基本工作单元，是给定代理应完成的小型、专注的任务。任务设计灵活，可根据需要进行简单和复杂的操作。任务的关键属性包括描述、分配给它的代理以及所需的任何特定工具。
CrewAI 的主要优势在于它的自动化协作框架，它可以帮助 AI agent 之间更好地合作，共同解决复杂问题。CrewAI 通过提供自动化设置，使代理之间的合作变得更加容易，从而提高了团队的效率和生产力。

### 实践
有了上述的知识之后我们再来是 crewAI 来搭建 agent 会变的容易，并且能够较好的理解  agent 的工作流。
“每天吃什么是个烦人的问题”在这里我们就以解决这个问题为目的来搭建一个 AI agent 来帮我们安排工作日的午餐。

#### 定义 agents 
在这个任务里我们定义两个 agent 一个用来选择餐厅，另外一个用来安排顺序。
```python
class FoodAgents():

    def restaurant_select_agent(self):
        return Agent(
            role='餐厅挑选达人',
            goal='根据预算和距离，餐厅好评度挑选合适的餐厅名单',
            backstory='擅长根据餐厅数据挑选就餐地方',
            tools=[
                SearchTools.search_internet,
                BrowserTools.scrape_and_summarize_website,
            ],
            llm=llm(),
            verbose=True
        )

    def keeper_agent(self):
        return Agent(
            role='每日午餐管家',
            goal='根据预算合理安排最近一周工作日 5 天的每日午餐就餐餐厅',
            backstory='在餐饮和营养方面拥有数十年经验的专家',
            tools=[
                SearchTools.search_internet,
                BrowserTools.scrape_and_summarize_website,
            ],
            llm=llm(),
            verbose=True
        )
```

#### 定义 tasks
给上述 agent 定义他们要完成的任务
```python
class FoodTasks():

    def seclet_task(self, agent, budget, district):
        return Task(
            description=dedent(f"""
            作为餐厅挑选达人，你会根据距离、预算、餐厅好评度、餐厅品类挑选出最适合
            工作日午餐就餐的餐厅。
            挑选出的餐厅价格不能超出预算范围，就餐的时间不能过长。
            用中文回复。
            
            预算:{budget}
            工作地:{district}
            """),
            agent=agent
        )

    def plan_task(self, agent, budget, district):
        return Task(
            description=dedent(f"""
            根据餐厅备选清单，你必须从就餐新鲜度和营养角度合理安排最近一周 5 天工作日每天的餐厅。
            你最终的答案是一个完整的包含工作日 5 天的就餐计划格式化为 markdown，包括每日就餐餐厅名称，餐厅简介。
            用中文回复。

            预算:{budget}
            工作地:{district}
            """),
            agent=agent
        )
```
#### 启动 agents
```python
class RestaurantPlan:
    def __init__(self, district, budget):
        self.district = district
        self.budget = budget

    def run(self):
        agents = FoodAgents()
        tasks = FoodTasks()

        restaurant_agent = agents.restaurant_select_agent()
        plan_agent = agents.keeper_agent()

        select_task = tasks.seclet_task(
            restaurant_agent,
            self.budget,
            self.district
        )

        plan_task = tasks.plan_task(
            plan_agent,
            self.budget,
            self.district
        )

        crew = Crew(
            agents=[restaurant_agent, plan_agent],
            tasks=[select_task, plan_task],
            verbose=True
        )
        result = crew.kickoff()
        return result


if __name__ == '__main__':
    budget = input(dedent("预算："))
    district = input(dedent("工作地点："))

    c = RestaurantPlan(district, budget)
    result = c.run()
    print("工作日吃什么\n")
    print(result)
```

### 分析工作流

  Entering new AgentExecutor chain...    

1. 下面的文本展示了让  LLM 推理的 prompt (为了便于展示省略了部分信息)  
```
    You are 餐厅挑选大人.
    擅长根据餐厅数据挑选就餐地方

    Your personal goal is: 根据预算和距离，餐厅好评度挑选合适的餐厅名单

    TOOLS:
    ------
    You have access to the following tools:

    Search the internet: Search the internet(query) - Useful to search the internet
        about a a given topic and return relevant results
    Scrape website content: xxxxxx`.

    Ask Question to Co-Worker: xxx`.

    To use a tool, please use the exact following format:

    Thought: Do I need to use a tool? Yes
    Action: the action to take, should be one of [Search the internet, Scrape website content, Delegate Work to Co-Worker, Ask Question to Co-Worker]
    Action Input: the input to the action
    Observation: the result of the action

    When you have a response for your task, or if you do not need to use a tool, you MUST use the format:

    Thought: Do I need to use a tool? No
    Final Answer: [your response here]
            This is the summary of your work so far:
    Begin! This is VERY important to you, your job depends on it!

    Current Task: 
    作为餐厅挑选大人，你会根据距离、预算、餐厅好评度、餐厅品类挑选出最适合
    工作日午餐就餐的餐厅。
    挑选出的餐厅价格不能超出预算范围，就餐的时间不能过长。
    用中文回复。

    预算:20-50
    工作地:长风大悦城   
```

2. LLM 推理结果
```
Thought: Do I need to use a tool? Yes
Action: Delegate Work to Co-Worker
Action Input: 每日午餐管家|询问长风大悦城附近的餐厅有哪些|工作地:长风大悦城, 餐厅品类:不限
```

省略中间的搜索和总结搜索结果过程...
3. 继续推理
```
You are 每日午餐管家.
在餐饮和营养方面拥有数十年经验的专家

Your personal goal is: 根据预算合理安排最近一周工作日5天的每日午餐就餐餐厅

TOOLS:
------
You have access to the following tools:

Search the internet: Search the internet(query) - Useful to search the internet
    about a a given topic and return relevant results
Scrape website content: Scrape website content(website) - Useful to scrape and summarize a website content

To use a tool, please use the exact following format:

Thought: Do I need to use a tool? Yes
Action: the action to take, should be one of [Search the internet, Scrape website content]
Action Input: the input to the action
Observation: the result of the action

When you have a response for your task, or if you do not need to use a tool, you MUST use the format:

Thought: Do I need to use a tool? No
Final Answer: [your response here]

		This is the summary of your work so far:
    
Begin! This is VERY important to you, your job depends on it!

Current Task: 询问长风大悦城附近的餐厅有哪些

This is the context you are working with:
工作地:长风大悦城, 餐厅品类:不限

Thought: Do I need to use a tool? Yes
Action: Search the internet
Action Input: "长风大悦城 附近 餐厅"Title: 长风大悦城- 上海餐厅,酒吧,夜生活,Spa,娱乐,购物 - Shanghai WOW!
Link: http://www.shanghaiwow.com/merchant/detail/id/2129
Snippet: 新天地超隐蔽酒廊，为你揭秘魔都名流的奢华派对！ 想要成功打入魔都精英人士的社交圈， 能顺利进入少数那几间高端会所，是关键所在。 近期我们在时尚潮人扎堆的新天地， ...

-----------------
Title: 1點點(長風大悅城店)餐廳、地址- 上海 - Trip.com
Link: https://hk.trip.com/travel-guide/shanghai-2-restaurant/dian-dian-chang-feng-jing-pan-an-chang-dian-61284402/
Snippet: 1點點(長風大悅城店)附近的餐廳 ; 福和慧. 4.8 · 條評價. HK$1249. 素食 ; 甬府（黃浦店）. 4.7 · 條評價. HK$1058. 江浙菜景觀餐廳 ; くろぎKurogi 黑木. 4.7 · 條評價. HK$3599.

-----------------
Title: 顺峰顺水顺德菜(长风大悦城店) - you.ctrip.com
Link: https://you.ctrip.com/food/2/78842745.html
Snippet: 距餐厅2km. 食廬(虹桥南丰城店). 4.5 ; 距餐厅2.1km. Erman岩烧牛排(虹桥南丰城店). 订. 4.8 ; 距餐厅1.8km. 瑞华樟园. 4.6 ...

-----------------
Title: 味千拉面(长风大悦城店)平面地图- 餐饮美食 - 城市吧
Link: https://ditu.city8.com/sh/cater/8d8mim794w7vb060f5?map
Snippet: 味千拉面(长风大悦城店)地址位于上海市普陀区大渡河路196号长风大悦城F1，靠近中江路、云岭东路、大渡河路和古北路，联系电话为(021)61437703。
```

4. LLM 推理结果
```
Do I need to use a tool? No
Final Answer: Some nearby restaurants to 长风大悦城 are: 1點點, 湘庭精致湖南菜, 味千拉面, 顺峰顺水顺德菜, 西贝莜面村, and 大肆兄.
```
5. 继续推理
```
You are 每日午餐管家.
在餐饮和营养方面拥有数十年经验的专家

Your personal goal is: 根据预算合理安排最近一周工作日5天的每日午餐就餐餐厅

TOOLS:
------
You have access to the following tools:

Search the internet: Search the internet(query) - Useful to search the internet
    about a a given topic and return relevant results
Scrape website content: Scrape website content(website) - Useful to scrape and summarize a website content
Delegate Work to Co-Worker: xxx.

Ask Question to Co-Worker: xxx.

To use a tool, please use the exact following format:

Thought: Do I need to use a tool? Yes
Action: the action to take, should be one of [Search the internet, Scrape website content, Delegate Work to Co-Worker, Ask Question to Co-Worker]
Action Input: the input to the action
Observation: the result of the action

When you have a response for your task, or if you do not need to use a tool, you MUST use the format:

Thought: Do I need to use a tool? No
Final Answer: [your response here]
		This is the summary of your work so far:
    The human asks the AI for nearby restaurants in the area of 长风大悦城 with no specific cuisine preference. The AI suggests 1點點, 湘庭精致湖南菜, 味千拉面, 顺峰顺水顺德菜, 西贝莜面村, and 大肆兄.
Begin! This is VERY important to you, your job depends on it!

Current Task: 
根据餐厅备选清单，你必须从就餐新鲜度和营养角度合理安排最近一周5天工作日每天的餐厅。
你最终的答案是一个完整的包含工作日5天的就餐计划格式化为 markdown，包括每日就餐餐厅名称，餐厅简介。
用中文回复。

预算:20-50
工作地:长风大悦城

This is the context you are working with:
根据每日午餐管家提供的附近餐厅信息，我在网上搜索了其中的一个“點點”，发现其评价并不错。因此我建议去“點點”就餐。
```
6. 推理结果
```
Thought: Do I need to use a tool? No
Final Answer: 

根据预算和工作地点，我建议以下餐厅：

周一：味千拉面 - 该店提供新鲜的拉面和汤，是一个健康营养的选择。

周二：大肆兄 - 这家店提供新鲜的沙拉和三明治，是一个轻松的午餐选择。

周三：湘庭精致湖南菜 - 该店提供健康营养的湖南菜，是一个美味和健康的选择。

周四：顺峰顺水顺德菜 - 这家店提供新鲜的广东美食，是一个丰富的午餐选择。

周五：西贝莜面村 - 该店提供新鲜的面条和汤，是一个健康营养的选择。

以上餐厅都在预算范围内，且都位于长风大悦城附近，可以保证就餐的新鲜度和营养角度的考虑。
```
上面的工作流包含了多次搜索和多次推理，其中还有错误这些信息我们没有全部展示。但从列出的关键步骤我们可以看到 
* LLM 根据 agent 输入的 prompt 产生 `thought` 比如“Do I need to use a tool? Yes”
*  LLM 判断需要执行的 `Action`，比如调用我们定义好的 tool“Search the internet”
* `Action Input` 作为执行动作的参数
* `Observation` 动作执行后的输出，继续提供给 LLM 进一步推理

### ReAct 问题
1. 不稳定    
非常依赖 LLM 的性能。即使目前最好的 LLM  gpt-4 仍然存在幻觉和内容输出不稳定的情况，这样导致最后的结果不够稳定;
2. 成本高     
如果使用推理性能好像闭源的 gpt-4 因为执行流程长，LLM 会被反复调用，这里的 token 成本会非常高；
3.  响应慢  
LLM 推理慢，加上反复多次调用，整个执行过程时间会比较长

目前 CrewAI 支持调用在 Ollama 框架下启动的语言模型，但是这块支持的还不够完善并且规模较小的 7B、13B 等开源模型性能不够好，导致整体 agent 生产环境的可用性还有待提高。这方面进展我们将持续关注。
