# AI Engineer System Design Assessment

This assignment continues the system design exercise. This page gives the problem, the requirements and the deliverables.

## The goal of the system

The system helps freight brokers in the US truckload market. It manages each load from before the pickup to the last delivery. Messages are the most important signal for this work, and operators use messages to manage their loads.

The broker is between the shipper, the carrier and the receiver of the load. The broker makes sure that the load is picked up and delivered on time and for the agreed price.

We have many broker clients. Each client can have its own procedure for a situation. We also have standard procedures. A standard procedure applies to all clients until a client asks for a change.

## Vocabulary

| Term | Meaning |
| --- | --- |
| SOP | Standard operating procedure. The instructions of a client for each situation. |
| Hero team | Our operations team. These people do the tasks that the agent cannot do, for example a phone call to a driver. |
| Dispatcher | The person at the carrier who controls the drivers. One dispatcher controls many drivers. |
| Stop | A location for pickup or delivery. Each stop has an appointment. A load has two or more stops. |
| Appointment | A fixed time, or a time window. In a time window, trucks arrive in the sequence they come (first come, first served). |
| ETA | Estimated time of arrival at the next stop. |
| Delay risk | The probability that the truck arrives after the appointment. The system calculates it again after each location ping. |
| BOL / POD / rate confirmation | Bill of lading: the driver gets it signed at pickup. Proof of delivery: the driver gets it signed at delivery. Rate confirmation: the contract between the broker and the carrier, with the price, the stops and the appointments. |
| TMS | Transportation management system. The main system of the broker. |

## The system

Design and build an agent that monitors the events of a load and does actions. The agent follows the SOP of the client for each situation and each stage of the load.

The agent does some tasks alone and shows what it did. For other tasks, it escalates to a person. An internal escalation goes to our Hero team. An external escalation goes to the broker.

### Inputs

- Email messages in the main thread of the load.
- SMS messages from the driver.
- Slack messages from the broker staff.
- Location pings. Each ping has the latitude, the longitude, the time and the delay risk that the system calculated.
- Timers that the agent set before.
- Attachments: BOL, POD, rate confirmation and receipts, as photos or PDFs. The agent must find the type of each document and get its key values.
- The load metadata, as JSON. It is available when the agent starts.

### External actions, for example

- Send an SMS to a contact.
- Send an email in the main thread, or start a new email.
- Send a message to the Slack channel of the broker.
- Write a note or a status in the TMS of the broker.
- Set a follow-up timer.

### Internal actions, for example

- Create a task for a Hero. A task can be urgent.
- Update the stage and the status of the load in our system.
- Send a message to the Heroes in our internal Slack channels about an important event.

### Stages of a load

Dispatched → To pickup → At pickup → To delivery → At delivery → Delivered (POD)

If a load has more stops, the middle stages occur again for each stop.

### Who talks to the agent

| Who | Channel | Description |
| --- | --- | --- |
| Driver | SMS | Sends short messages. Often answers late or does not answer. |
| Carrier dispatcher | Email, sometimes SMS | Writes to the broker in the main email thread. For the carrier, the agent is the broker. Sends updates from the driver, for example the ETA. |
| Broker staff | Email, Slack | Our client. Gets a copy of the email thread. Gets alerts in Slack. |
| Hero team | Internal tasks | Our operations team. Does the tasks that the agent cannot do. |

Each load has one main email thread. Usually the broker, the dispatcher and the agent are in this thread. Each person in the thread can write at any time.

## Load metadata

This is an example. Your design can use other fields if it states them.

```json
{
  "load_id": "481207",
  "broker": { "id": "northline", "name": "Northline Logistics" },
  "shipper": "Riverbend Foods",
  "carrier": { "name": "Prairie Haul LLC", "mc_number": "778120" },
  "commodity": "Canned tomato sauce, 38,000 lb, dry van",
  "stage": "to_pickup",
  "delay_risk": "low",
  "contacts": [
    { "id": "drv_20931", "role": "driver", "channels": ["sms"] },
    { "id": "dsp_4410", "role": "dispatcher", "channels": ["email"] },
    { "id": "brk_0087", "role": "broker", "channels": ["email", "slack"] }
  ],
  "stops": [
    {
      "sequence": 1,
      "type": "pickup",
      "name": "Riverbend plant",
      "address": "Stockton, CA",
      "timezone": "America/Los_Angeles",
      "appointment": { "type": "window", "start": "2026-10-13T06:00", "end": "2026-10-13T14:00" }
    },
    {
      "sequence": 2,
      "type": "delivery",
      "name": "Valley DC",
      "address": "Reno, NV",
      "timezone": "America/Los_Angeles",
      "appointment": { "type": "fixed", "time": "2026-10-14T09:30" }
    }
  ],
  "instructions": "Call 1 hr before arrival. PO 55821 required at gate."
}
```

### You can assume

- The SOP of each client is a set of Markdown files in plain English. Each file is about one topic, like a chapter of a manual. All files of one client are approximately 100 pages.
- Our integrations team connects Slack, email, SMS and the TMS (transportation management system) of the client. These connections are internal services that you call with HTTP or with queues. You can use mocks for them.
- The agent identifies each person with a contact ID. The message service changes the ID into a phone number or an email address.
- Clients define their own procedures for the main stages of the load, for example when the driver goes to a stop or is at a stop.
- We do not know all situations before they occur. The agent must know when **not to act**. For example, the driver sends "ok", but the agent did not ask a question. The correct action is to do nothing.
- We use AWS, but your solution **does not have to use** AWS or any other cloud.

### Requirements

| Volume | 100,000 loads each month, with 50 to 100 inbound messages for each load. Most messages arrive in US business hours. The volume will increase. |
| --- | --- |
| Load duration | A load is active for 2 days to 2 weeks. |
| Response time | One agent run must take **5 minutes or less**, from the event to the last action. This includes the infrastructure time. |
| LLM cost | On average, the LLM inference for one load must cost approximately **$1 or less**, for the full life of the load. We charge each client a fixed price for each load. |
| Clients | The system supports many brokers. The number of procedures, situations and channels for each client will increase. |
| SOP editors | People without a technical background write and change the SOPs, for example Heroes and our customer teams. An AI engineer must **not** be necessary to change an SOP. |

## How the instructions are different

Approximately 60 to 70% of the procedure is the same for all clients. The other part is different for each client. Sometimes it is also different for each type of load. We add new clients frequently. A client often changes its procedure in the first weeks.

| Client | Event | Procedure |
| --- | --- | --- |
| Client A | Delay risk changes to high | Send an SMS to the driver to get the ETA. If there is no ETA after 30 minutes, send the SMS again. After two SMS with no ETA, send an email to the dispatcher in the main thread. Then create a Hero task. |
| Client B | Delay risk changes to high | Send one SMS to the driver. If there is no ETA after 30 minutes, send an alert to the Slack channel of the broker. Do not contact the dispatcher. |
| Client B, refrigerated loads | Driver leaves the pickup | Ask the driver for the trailer temperature and the seal number. |

## The situation

Your code must handle this sequence for load #481207. The client is Client A. The Client A procedure for high delay risk is:

> Send an SMS to the driver to get the ETA. If there is no ETA after 30 minutes, send the SMS again. After two SMS with no ETA, send an email to the dispatcher in the main thread. Then create a Hero task.
> 

| Time | Source | Event |
| --- | --- | --- |
| 07:00 | Ping | A location ping arrives. The delay risk for the pickup changes from low to high. |
| 07:01 | Agent | Sends an SMS to the driver: "What time will you arrive at the pickup?" |
| 07:12 | SMS | The driver answers with a question: "What's the PO number?" The driver does not give the ETA. |
| 07:13 | Agent | Finds the PO number in the load metadata and sends it to the driver. The ETA request is still open. |
| 07:31 | Timer | The driver did not send the ETA. The agent asks for the ETA again. |
| 08:01 | Timer | The driver did not send the ETA after two requests. |
| 08:02 | Agent | Sends an email to the dispatcher in the main thread: "Your driver does not answer. Please send the ETA." |
| 08:02 | Agent | Creates a task for the Hero team to call the driver. |

At each step, the agent must decide from what happened before: its own actions and the past messages of the load.

## Deliverables

Send one code repository. It must contain:

- **Documentation:** the design of the full system, with architecture diagrams. Answers to the questions below.
- **Agent code:** an agent that handles the situation above, or a part of it. The agent must use memory of its past actions and of past messages to select the next action.
- **Evals:** test cases that show the agent takes the correct action at each step of the situation. Include a case where the correct action is to do nothing.
- **Instructions to run:** the steps to run the agent and the evals on a local computer.

You can use mocks for Slack, email, SMS, the TMS and our internal system. You do not have to build the full system. The documentation must describe the parts that you do not build.

## Questions to answer in the documentation

### Agent architecture

1. What is the architecture of your agent? What are the alternatives?
2. How does the agent read documents, find their type and get their key values?

### Instructions

1. How do you organize the SOPs of many clients? The standard procedure applies to all clients until a client changes it.
2. How does the agent find the correct SOP files for the current event? What are the advantages and disadvantages of your method?
3. People without a technical background write and change the SOPs. How does your design make this safe? You do not have to build an editor or a platform. Describe the design.

### Memory

1. How does the agent know its past actions and the past messages of the load?
2. At 07:13, how does the agent remember that the ETA request is still open?
3. How does a follow-up timer work? What does the agent see when the timer starts it?

### Evals

1. How do you make sure that the system works correctly in production?
2. A client changes its procedure. How do you make sure that other behavior does not break?
3. You change the LLM. How do you make sure that the system does not break?
4. Clients have different procedures and different complexity. How do you organize the evals?

### Scale, response time and cost

1. How does your design keep each agent run at 5 minutes or less?
2. The volume increases ten times. What must change?
3. How do you keep the LLM cost at approximately $1 or less for each load? You do not have to implement this.