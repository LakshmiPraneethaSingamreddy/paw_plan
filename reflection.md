# PawPal+ Project Reflection

## 1. System Design
The intial 3 core actions the user should be able to perform are
1) The user can add/ remove a pet
2) The user can edit(add/remove) the tasks
3) The user can check the schedule at any point of time during the day 

**a. Initial design**

- Briefly describe your initial UML design.

    My intial UML has only 3 classes where the classes and relationships between them describe the basic and important functionality of the app.
- What classes did you include, and what responsibilities did you assign to each?

    The classes i have included in my initial UML are: 1) Owner, 2) Pet and 3) Scheduler.
    the responsibilities of these classes are:
    1) Owner - can add/remove the pet, can edit(add/remove) tasks, can view schedule, provides availability window and preferences
    2) Scheduler - create schedule, can edit schedule, generates explanation, ranks tasks based on priority and keep tracks of multiple pets
    3) pet - has name, age, height and weight.

**b. Design changes**

- Did your design change during implementation?

    Yes , during the implementation my designed has changed. I have added some more classes and the corresponding required attributes to make the system more manageable and also for clean system design.
- If yes, describe at least one change and why you made it.
 
    1) I have created seperate classes for owner preferences and Availability window so that the system logic will not become complicated.
    2) I have added Petcare app class as the main interface, so that it will be the entry point where the owner interacts with the app.
    3) I have added Scheduling constraint, Daily schedule and schedule item classes so that the edits to the schedule are manageable.
    4) I have created a seperate PlanExplanation class, so that the explanation of why that plan has choosen will be transparent.
    5) I have included a CareTask class, becuase a pet can have many tasks scheduled for that day and something needs to keep track of these.
    6) I have also added a multi-agent architecture with AgentRole, where each role like scheduler, explanation, and task management has a clear boundary and responsibility. This keeps things clean and makes it easier to extend later.
    7) Finally I split the UI into seperate files like app.py, app_ui.py, app_helpers.py and app_agents.py so that the code is organized and not all in one place.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?

    For the scheduler I have taken the availabiltiy, priority and preferences of the owner into consideration. I have also added task category, flexibility, recurrence frequency and time windows (earliest start and latest end) as constraints so the scheduler knows exactly when each task can run.

- How did you decide which constraints mattered most?
   
    I have decided to give more weightage to the availability and priority, because the tasks should be completed when the owner is available and the high priority tasks should be completed first with in their scheduled time(like vet appointments, feeding as they can't be postponed). And then if the tasks are flexible, and cannot be fit in their scheduled slot, I assigned them to the next available time frame, because I want nothing to be skipped unless until I can't fit that task anywhere for that day. 

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.

    The main tradeoff that my schedule makes is that if a task is **"low priority"** and is **"flexible"**, then it will first schedule the tasks that are high priority, then schedule the remaining tasks later, and if they can't fit in their requested time slot, since they are flexible they are pushed to the next available time slot. And on top of this I also have a AI based scheduler that tries to build the schedule, and if it fails within the retry budget, the rule-based fallback scheduler takes over and builds the schedule instead.

- Why is that tradeoff reasonable for this scenario?

    I think this tradeoff is reasonable in this scenario. For example, consider three tasks within the 8:00 a.m. to 10:00 a.m. window: breakfast feeding (20 minutes, high priority, non-flexible), a vet appointment (90 minutes, high priority, non-flexible), and a morning walk (30 minutes, medium priority, flexible). Since feeding and the vet appointment are both high priority and non-flexible, they must be scheduled first. After placing those two tasks, only 10 minutes remain in the original window, which is not enough time for the full walk. Because the morning walk is flexible, the scheduler shifts it to the next available slot, from 9:50 a.m. to 10:20 a.m., instead of dropping it. This behavior prioritizes critical care while still completing less urgent flexible tasks whenever possible.

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?

    I used the AI tools for code writing, debugging, refactoring and test case generation during this project. I also actually integrated AI into the app itself through a LLMExplanationAgent that takes the rule-based plan explanations and rewrites them in a more human readable way when the user clicks the "Explain with AI" button.

- What kinds of prompts or questions were most helpful?

    I observed that the clear prompting of what we actually want helps in acheiving better functionality of the app. And asking the questions about why something is failing or how can we optimize the functionality further, or just asking the agent to generate plan on what next steps should be are really helpful as they give clear picture of what is happening with the code.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.

    When I was trying to integrate the scheduler with an LLM to support multi-mode schedule generation, where the app could use either the deterministic scheduler or the LLM to build the schedule, it raised so many errors. Copilot kept changing the code again and again but nothing was actually working and it was going in circles. So I had to stop the chat and made a hard decision to keep only the deterministic model for schedule generation and instead use the LLM just for generating a summary for the plan explanation. I kept the full LLM-based schedule generation as a future improvement because I felt that forcing it at that point was just breaking more things than it was fixing.

- How did you evaluate or verify what the AI suggested?

    I first ask on the Ai to explain fully what it suggests and then verify if it aligns with my goal and if it does I will ask it to generate a plan on how we are going to implement that. If I am satisfied with the plan, then I will proceed with the implementation and then I will ask it to generate some tests and I will also manually test the newly added functionality by myself.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?

    I have tested the functionalities that I want my app to perform. I have tested whether the user can enter/edit/delete their details, user can add/edit/remove their pets, if user can add multiple pets, the core scheduling and ordering of tasks, how recurrent tasks are generated(daily, weekly, and custom recurrence like selected weekdays or every N days), whether the availability and preferences are taken into consideration or not, schedule regeneration and conflict handling, how the schedule plan explanations are done, task validation guardrails that reject invalid inputs and show repair hints, inline task editing and removal from the task list, and task completion tracking where completed tasks show strikethrough.

- Why were these tests important?

    These tests are important because they verify that the app is actually delivering the functionality it is designed to provide. They also help catch gaps, edge cases, and unfinished logic, so I can identify and fix loose ends in the code before release.
**b. Confidence**

- How confident are you that your scheduler works correctly?

    I am highly confident that my scheduler works correctly because it is supported by a strong implementation strategy and rigorous testing. The combination of careful design decisions and comprehensive test coverage gives me confidence that the core functionality behaves reliably across expected scenarios. I also have a diagnostics panel built into the UI that shows how many scheduling attempts were made, how many retries happened, and whether the fallback was used, so I can actually see what the scheduler did internally.

- What edge cases would you test next if you had more time?

    If I had more time, I would implement a database layer so user data can be stored persistently instead of only in session state. After that, I would add targeted tests for data persistence, including save/retrieve flows, update consistency, and correct loading behavior across app restarts. This would make the system more reliable for real-world usage and help ensure data integrity over time.

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

    I feel the project went very well overall, and I am most satisfied with the UI design and the functionality it delivers. I am especially happy with the scheduler diagnostics panel and the AI explanation feature because they make the app feel more transparent and interactive. I mean, the user can actually see what the scheduler did and why it made those decisions, which I think is really cool.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

    I would improve the app by adding database integration so it becomes a true end-to-end system, with persistent user data storage instead of session-only state. And I would also improve the AI scheduling so it handles more complex edge cases and doesn't need to fall back to the rule-based scheduler as often.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

    I learned that UML diagrams play a critical role in app development because they provide a clear roadmap of what needs to be built. They help keep the implementation focused, reduce scope drift, and prevent unnecessary complexity by guiding decisions throughout the project. And I also learned that integrating AI into an actual product is very different from just using AI to write code. You have to think about when the AI should run, what happens when it fails, and how to show the user what it did, which is something I had not thought about before.
