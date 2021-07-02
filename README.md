![Licence](https://img.shields.io/github/license/lawRossi/broca)
![Python](https://img.shields.io/badge/Python->=3.6-blue)

# 中文README

## 简介
   Broca是一个轻量的对话系统框架，如下图所示，该框架包含任务引擎和Faq引擎，同时支持任务对话和Faq对话。
当接受用户的消息时，中控组件负责将消息分发给任务引擎或faq引擎。任务引擎在设计和实现上借鉴了rasa框架，
但比rasa更轻量，也更容易使用，可以支持多个agent。Faq Agent基于语义匹配技术实现，可实现问题准确又高效的检索。

   ![](resource/img/arch.png)

## 安装

把代码克隆到本地，然后可通过以下命令进行安装：

    python setup.py install

然后通过pip 安装依赖：

    pip install -r requirements.txt

## 快速上手
    
在命令行输入以下命令初始化一个项目：
 
    broca init --project_name demo --project_type task
然后可看到一个初始化的项目模板，目录结构如下：

![](resource/img/directory_tree.png)

初始化项目包含了一个初始的agent，在agent目录下，其中agent_config.json是该agent的配置文件，skills.py用于定义该agent的技能。controller.py中定义了中控组件，是项目的启动文件。intent_patterns.json用于定义意图识别模板。task_engine_config.json是对话引擎的配置文件。

我们通过实现两个简单技能来完成一个简单的demo，编辑agent/skills.py，写入以下代码：

```python
from Broca.task_engine.skill import Skill


class GreetSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "greet_skill"
        self.trigger_intent = "greet"
        self.intent_patterns = ["hi", "hey", "你好"]

    def _perform(self, tracker):
        self.utter("你好", tracker.sender_id)
        return []


class IntroductionSkill(Skill):
    def __init__(self):
        super().__init__()
        self.name = "introduce_skill"
        self.trigger_intent = "what_can_you_do"
        self.intent_patterns = ["你能做(什么|啥)[？?]?"]

    def _perform(self, tracker):
        self.utter("我可以陪你聊天", tracker.sender_id)
        return []
```
接着我们可以通过运行controller.py来测试我们的demo：

![](resource/img/demo.png)
