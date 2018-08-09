import random
import requests
import sys
import discord
import binascii
import json
from collections import deque
from jsonrpc_requests import Server

from models import Transaction, TipJar

config = json.load(open('config.json'))

class CCXServer(Server):
    def dumps(self, data):
        data['password'] = config['rpc_password']
        return json.dumps(data)

rpc = CCXServer("http://{}:{}/json_rpc".format(config['rpc_host'], config['rpc_port']))
daemon = CCXServer("http://{}:{}/json_rpc".format(config['daemon_host'], config['daemon_port']))
CONFIRMED_TXS = []


def get_supply():
    lastblock = daemon.getlastblockheader()
    bo = daemon.f_block_json(hash=lastblock["block_header"]["hash"])
    return float(bo["block"]["alreadyGeneratedCoins"])/1000000


def format_hash(hashrate):
    i = 0
    byteUnits = [" H", " KH", " MH", " GH", " TH", " PH"]
    while (hashrate > 1000):
        hashrate = hashrate / 1000
        i = i+1
    return "{0:,.2f} {1}".format(hashrate, byteUnits[i])


def gen_paymentid(address):
    rng = random.Random(address+config['token'])
    length = 32
    chunk_size = 65535
    chunks = []
    while length >= chunk_size:
        chunks.append(rng.getrandbits(chunk_size * 8).to_bytes(chunk_size, sys.byteorder))
        length -= chunk_size
    if length:
        chunks.append(rng.getrandbits(length * 8).to_bytes(length, sys.byteorder))
    result = b''.join(chunks)

    return "".join(map(chr, binascii.hexlify(result)))


def get_deposits(session):
    # get the current block height
    # we only want to insert tx after 10 blocks from the tx
    data = daemon.getlastblockheader()
    height = int(data["block_header"]["height"])
    print("INFO: Current blockchain height is {}".format(height))
    # scan for deposits
    print("scanning the blockchain for deposits")
    print("getting list of payment id's in the tipjar database")
    allPID = session.query(TipJar).all()
    thePID = 0
    totalPID = len(allPID)
    for thePID in range(0,totalPID):
        currentPID = allPID[thePID].paymentid      
        print("INFO: checking PID {}".format(currentPID))
        params = {"payment_id": currentPID}
        data = rpc.get_payments(params)
        #go through each transaction and them to the confirmed transactions array
        for tx in data['payments']:         
            unlockWindow = int(tx["block_height"]) + 10
            if tx['tx_hash'] in CONFIRMED_TXS: # if its already there, ignore it
                continue
            if unlockWindow < height: # its a confirmed and unlocked transaction
                CONFIRMED_TXS.append({'transactionHash': tx['tx_hash'],'amount': tx['amount'], 'ready':True, 'pid':currentPID})
                print("CONF: confirmed tx {} for {} ccx at block {}".format(tx['tx_hash'],tx['amount'],tx['block_height']))              
            else :
                toUnlock = unlockWindow - height
                print("UNCF: unconfirmed tx {} for {} ccx will unlock in {} blocks".format(tx['tx_hash'],tx['amount'],toUnlock))               
    for i,trs in enumerate(CONFIRMED_TXS): #now we go through the array of all transactions from our registered users
        processed = session.query(Transaction).filter(Transaction.tx == trs['transactionHash']).first()
        amount = 0
        print("INFO: looking at tx: " + trs['transactionHash'])
        if processed: # done already, lets ignore and remove it from the array
            print("INFO: already processed: " + trs['transactionHash'])
            CONFIRMED_TXS.pop(i)
            continue
        likestring = trs['pid']
        balance = session.query(TipJar).filter(TipJar.paymentid.contains(likestring)).first() #get the balance from that PID
        print("INFO: Balance for pid {} is: {}".format(likestring,balance))
        if not balance:
            print("user does not exist!")
            continue
        amount = trs['amount']       
        change = 0
        if trs['pid']==balance.paymentid: # money entering tipjar, add to user balance
            print("UPDATE: deposit of {} to PID {}".format(amount,balance.paymentid))
            change += amount
            try:
                balance.amount += change
            except:
                print("no balance, setting balance to: {}".format(change))
                balance.amount = change
        print("new balance: {}".format(balance.amount))
        session.commit()
        if balance:
            nt = Transaction(trs['transactionHash'], change, trs['pid'])
            CONFIRMED_TXS.pop(i)
            yield nt 
            

def get_fee(amount):
    return 100


def build_transfer(amount, transfers, balance):
    print("SEND PID: {}".format(balance.paymentid[0:58] + balance.withdraw))
    params = {
        'fee': get_fee(amount),
        'paymentId': balance.paymentid[0:58] + balance.withdraw,
        'mixin': 3,
        'destinations': transfers
    }
    return params


REACTION_AMP_CACHE = deque([], 500)


def reaction_tip_lookup(message):
    for x in REACTION_AMP_CACHE:
        if x['msg'] == message:
            return x


def reaction_tip_register(message, user):
    msg = reaction_tip_lookup(message)
    if not msg:
        msg = {'msg': message, 'tips': []}
        REACTION_AMP_CACHE.append(msg)

    msg['tips'].append(user)

    return msg


def reaction_tipped_already(message, user):
    msg = reaction_tip_lookup(message)
    if msg:
        return user in msg['tips']
