import datetime
import logging
import os
from random import randint
import uuid

from bottle import Bottle
import pymongo
from pytz import timezone
import sendgrid
from twilio.rest import TwilioRestClient


level = logging.INFO
handler = logging.StreamHandler()
handler.setLevel(level)
handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger = logging.getLogger('info')
logger.addHandler(handler)
logger.setLevel(level) #even if not required...


TWILIO_ACCOUNT_SID = os.environ['TWILIO_ACCOUNT_SID']
TWILIO_AUTH_TOKEN = os.environ['TWILIO_AUTH_TOKEN']
TWILIO_FROM = os.environ['TWILIO_FROM']
SENDGRID_API_KEY = os.environ['SENDGRID_API_KEY']
DATABASE_URL = os.environ['DATABASE_URL']
DATABASE_NAME = os.environ['DATABASE_NAME']


def bulkloadcollection(collectionid, startpoint=1):
    """
    bulk load the db with pipe-delimited info from bulkload.txt
    :param startpoint: skip lines in the file until this line number (1-based)
    """
    collection = _getcollection(collectionid)
    i = 1
    with open('bulkload.txt') as filedata:
        lines = filedata.readlines()
        for line in lines:
            if i < startpoint:
                print('skipping ' + str(i) + '...')
                i += 1
                continue
            note = line.split('|')[0]
            # mediaurl is optional
            try:
                mediaurl = line.split('|')[1].replace('\n', '')
            except BaseException:
                mediaurl = None
            post = {'orderid': i, 'id': str(uuid.uuid4()), 'text': note, 'mediaurl': mediaurl}
            collection.insert_one(post)
            logger.info('uploaded #[{0}]: {1}'.format(str(i), note))
            i += 1


def _getcollection(collectionname):
    """get mongo collection by name"""
    client = pymongo.MongoClient(DATABASE_URL)
    return client[DATABASE_NAME][collectionname]


class Queue(object):
    """represents a message queue"""
    @staticmethod
    def getallqueues():
        """read the master collection to build a collection of queues"""
        for masteritem in _getcollection('master').find():
            yield Queue(masteritem)

    def getdailytimestamp(self):
        """get the current day in iso format"""
        return datetime.datetime.now(timezone(self.timezone)).date().isoformat()

    def gethourlytimestamp(self):
        """get the current day plus hour"""
        return self.getdailytimestamp() + '-' + str(datetime.datetime.now(timezone(self.timezone)).hour)

    def getminutetimestamp(self):
        """get the current day plus hour plus minute"""
        return self.gethourlytimestamp() + '-' + str(datetime.datetime.now(timezone(self.timezone)).minute)

    def getsecondtimestamp(self):
        """get the current day plus hour plus minute plus second"""
        return self.gethourlytimestamp() + '-' + str(datetime.datetime.now(timezone(self.timezone)).minute) + '-' + str(datetime.datetime.now(timezone(self.timezone)).second)

    def visit(self):
        """visit the queue. return 3 if too early, 2 if already sent, 1 if random not met, 0 if sent (in that order of precedence)"""
        starttime = datetime.time(hour=self.starthour, minute=self.startminute, tzinfo=timezone(self.timezone))
        now = datetime.datetime.now(timezone(self.timezone))
        # assemble the hour/minute for the starttime for today
        start = datetime.datetime.combine(now.date(), starttime)
        if now < start:
            logger.info('[{2}] now: [{0}] < start: [{1}] so we wont bother yet.'.format(now, start, self.collectionname))
            return {'val': 3, 'msg': 'tooearly'}
        timestamp = self.timestampfunction()
        for item in self.collection.find({'sent': timestamp}):
            logger.info('[{1}]: A message already exists with timestamp [{0}]'.format(timestamp, self.collectionname))
            return {'val': 2, 'msg': 'alreadysent'}
        randomtest = randint(0, self.randomlevel)
        if randomtest != 0:
            logger.info('[{1}]: Random requirement NOT met: [{0}] != 0'.format(randomtest, self.collectionname))
            return {'val': 1, 'msg': 'randomnotmet'}
        # all the pre-reqs are satisfied. gather a message and send it
        for item in self.collection.find({'sent': {'$exists': False}}).sort('orderid'):
            logger.info('Random requirement met. Sending message')
            logger.info('Item: [{0}]'.format(repr(item)))

            if self.deliverymethod == 'txt':
                txtclient = TwilioRestClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                for recipient in self.target.split(','):
                    logger.info('[{0}]: Sending txt message to [{1}]'.format(self.collectionname, recipient))
                    if item['mediaurl']:
                        txtclient.messages.create(to=recipient, from_=TWILIO_FROM, body=item['text'], media_url=item['mediaurl'])
                    else:
                        txtclient.messages.create(to=recipient, from_=TWILIO_FROM, body=item['text'])

            if self.deliverymethod == 'email':
                subject = (item['text'] or 'picture enclosed')[:72]
                toaddresses = [{'email': x} for x in self.target.split(',')]
                #mail = Mail(Email("talktopete@gmail.com"), subject, Email(self.target), Content("text/html", "<html><body><img src='"+item['mediaurl']+"' /></body></html>"))
                data = {
                    'personalizations': [{'to': toaddresses, 'subject': subject}],
                    'from': {'email': 'talktopete@gmail.com'},
                    'content': [{'type': 'text/html', 'value': "<html><body><img src='"+item['mediaurl']+"' /></body></html>"}]
                }
                logger.info('[{0}]: Sending email message: {1}'.format(self.collectionname, data))
                response = sendgrid.SendGridAPIClient(apikey=SENDGRID_API_KEY).client.mail.send.post(request_body=data)
                logger.info(response.status_code)
                logger.info(response.body)

            logger.info('Updating mongodb')
            self.collection.update_one({'id': item['id']}, {'$set': {'sent': timestamp}})
            return {'val': 0, 'msg': 'OK'}

    def __init__(self, masteritem):
        """initialize a queue given a master item"""
        self.randomlevel = int(masteritem['randomlevel'])
        self.target = masteritem['target']
        self.timezone = masteritem['timezone']
        self.starthour = int(masteritem['starthour'])
        self.startminute = int(masteritem['startminute'])
        self.collectionname = masteritem['collectionname']
        self.collection = _getcollection(masteritem['collectionname'])
        self.deliverymethod = masteritem['deliverymethod']
        if masteritem['frequency'] == 'daily':
            self.timestampfunction = self.getdailytimestamp
        elif masteritem['frequency'] == 'hourly':
            self.timestampfunction = self.gethourlytimestamp
        elif masteritem['frequency'] == '10sec':
            self.timestampfunction = self.getsecondtimestamp
        else:
            self.timestampfunction = self.getminutetimestamp


app = Bottle()
@app.get('/ping')
def ping():
    """app endpoint"""
    logger.info('received ping')
    result = [{'collection': repr(x.collection), 'result': x.visit()} for x in Queue.getallqueues()]
    return repr(result)


#logger.info(repr(ping()))
app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
#bulkloadcollection('annie')
#sendone()
#print(ping())
