# txt24 - scheduled message/image delivery app
Assemble a mongodb collection of pre-authored messages and use this app to deliver them on a scheduled cadence with optional level of random timing

### features
- send queues of messages for email or sms
- support for sms media attachments (images)
- support for email html/configurable subjects
- support for multiple queues
- each queue enables:
  - multiple recipients
  - multiple options for delivery cadence with optional randomization factor
  - media type (email or sms)
- sms delivery via twilio
- email delivery via sendgrid
- works as a rest api where the delivery action is invoked via http get request
- included bulk upload utility which reads a pipe-delimited file and adds items to a queue

### background
i was in search of an app which could disperse a photo album via text one picture per day for an extended period of time. Not finding anything quite like this on the market it became clear that a mashup of free online services plus some orchestration via python could achieve the desired effect.

### technical overview
The cycle is controlled by a cron-type schedule which will invoke an http get request
The get request initiates a connection to a mongo db to read a 'master' collection containing one item per queue. Each item in the master collection has the following fields:
- **collectionname**: the name of the collection containing the queued messages
- **frequency**: (daily|hourly|10sec) dictates how frequently the sending action should be considered. when a queue is visited and a message is already sent in near recent history then the frequency dictates if another message should be sent or not
- **randomlevel**: enables random behavior in to the delivery timing. with each cycle before sending a message from the queue a random number is generated in the range of 0-randomlevel. if the generated number!=0 then the message is not sent in this cycle
- **deliverymethod**: (txt|email)
- **target**: if deliverymethod==txt this is a comma-separated list of phone numbers. if deliverymethod==email this is a comma-separated list of emails
- **timezone**: python timezone encoding
- **starthour**: dont send messages before this hour (with respect to timezone)
- **startminute**: dont send messages before this minute (with respect to timezone)

Each queue is a collection in the mongo db with the following schema:
- **orderid**: dictates the order in which items are sent (number)
- **sent**: the timestamp dictating when the message was sent (blank if not yet sent)
- **text**: for email this becomes the subject. for sms this is the text message (can be blank)
- **mediaurl**: for email this will be an html-embedded image. for txt this is the image displayed included in the text (can be blank but both text and mediaurl cannot both be blank for the same message)

### recommended setup
I use heroku to host the app and an mLab dyno to host the text content. An account with sendgrid and twilio are required to use email and sms and the credentials are supplied via environment variables.

### flow diagram
The following flow diagram describes general function
(created using vim DrawIt! diagramming plugin)

```                                                                      
                                   +-------------------------------------+
                                   v                                     |
 *********                    +-----------+    +------------------+      |
*activation* ----http get---> |  /ping    |--->|connect to mongodb|      |
 *********                    +-----------+    +--------+---------+      |
                                                           |             |
           +-----------------------------------------------+             |
           |                                                             |
           |                                           +-----------------------------+
           |                        +----------------->|return results for all queues|
           |                        |                  +-----------------------------+
           v                        |
  +--------+-------------+   +--------------+  +------------------+
  |read master collection|-->|for each queue|->|too early to send?|   
  +----------------------+   +------+-------+  +---+--------------+
                                    ^              |      |
                                    |              |      |
                             +--------------+      |      |
                             |append queue  |      |      |
                             |send result   |      |      |
                             +--------------+      |      |
                                    ^              |      |
  +----------------------+          |              |      |
  |is message sms or mail|          +-------yes----+      no
  +----------------------+          |                     |
   ^  | |                           ^                     v
   |  | email                       |           +-----------------+
   |  | |                           +-------yes-|already sent for |
   |  | +-------------------+       |           |this cycle?      |   
   |  | | send via sendgrid |-+     |           +-----------------+
   |  | +-------------------+ |     ^                     |no
   |  |sms                    v     |                     v
   |  +---------------+       |     |           +------------------+
   |  |send via twilio|-------+     +-------yes-|random guess      |
   |  +---------------+       |     |           |failed?           |
   |    +----------------<-----     +-+         +------------------+
   |    |                             |                   |
   |  +-v--------------------------+  ^ ---------+        |no
   |  |update message in collection|  |      no msg       |
   |  |set sent=timestamp          |--+          |        v
   |  +----------------------------+            +------------------+
   |                                            |get next message  |
   +---------------------------------msg--------|in queue not sent |
                                                +------------------+
```
