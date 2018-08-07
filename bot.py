import asyncio

import discord
from discord.ext.commands import Bot, Context
import requests

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from poolModels import pool, poolBase
from models import Wallet, TipJar, Base, Transaction
from utils import config, format_hash, gen_paymentid, rpc, daemon, \
        get_deposits, get_fee, build_transfer, get_supply, \
        reaction_tip_register, reaction_tipped_already

HEADERS = {'Content-Type': 'application/json'}

### DATABASE SETUP ###
engine = create_engine('sqlite:///ccxbot.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

### POOL DATABASE SETUP ###
poolEngine = create_engine('sqlite:///poolData.db')
poolBase.metadata.create_all(poolEngine)
poolSession = sessionmaker(bind=poolEngine)
session2 = poolSession()

client = Bot(
        description="{} Discord Bot".format(config['symbol']),
        command_prefix=config['prefix'],
        pm_help=False)


@client.event
async def on_member_join(member):
    await send_join_pm(member, client)



async def wallet_watcher():
    await client.wait_until_ready()
    while not client.is_closed:      
        for tx in get_deposits(session):
            session.add(tx)
            try:
                session.commit()
            except:
                session.rollback()
            balance = session.query(TipJar).filter(TipJar.paymentid == tx.paymentid).first()
            if not balance:  # don't do for withdrawals from jar (basically tips)
                return
            good_embed = discord.Embed(title="Deposit Recieved!",colour=discord.Colour(0xD4AF37))
            good_embed.description = "Your deposit of {} {} has now been credited.".format(tx.amount/config['units'], config['symbol'])
            print("TRANSACTION PID IS: " + tx.paymentid)
            good_embed.add_field(name="New Balance", value="{0:,.2f}".format(balance.amount/config['units']))
            user = await client.get_user_info(str(balance.userid))
            try:
                await client.send_message(user, embed=good_embed)
            except:
                continue
        await asyncio.sleep(119)  # just less than the block time

client.loop.create_task(wallet_watcher())

@client.event
async def on_ready():
    print("Bot online!")


### TEST COMMANDS ###
# test to see if we can a list of users online
# and then to a rain function which sends money from a different wallet to everyone
# and to test getting a welcome dm

async def send_join_pm(member, client):
    """
    Sends a welcome private message to joined members.
    """

    if member.bot:
        return

    currently_online = ""
    for m in member.server.members:
        if not m.status.__str__() == "offline":
            if m.roles.__contains__(discord.utils.get(m.server.roles, name="core team")):
                currently_online += ":white_small_square:  " + m.mention + "\n"

    await client.send_message(member,
                              "**Hey, " + member.name + "! Welcome to the Conceal Discord! :)**\n\n"
                              "If you're new here and have some questions head over to the  **#faq** channel for an introduction to the project and answers to common questions.\n"
                              "You can also head over to the **#annoucements##** channel and see the latest news on where we are and what we are doing.\n"
                              "If you have more questions, look for one the admins or devs\n\n"
                              "**Devs currently online:**\n\n%s\n\n"
                              "You can also use this bot to get more information:\n"
                              "Use the command `.help` to get list of commands.\n"
                              "You can also see current network information with `.stats` or other specific commands like `.hashrate`, `.height`, `.difficulty`, and `.supply`\n"
                              "Don't forget to register your wallet address with the bot with the command `.registerwallet` so you can recieve tips.\n"
                              "If you want to send tips then type `.deposit` after you register your wallet address and transfer some funds to your TipJar.\n"                              
                              % currently_online)


@client.command(pass_context=True)
async def price(ctx, exchange=None):
    err_embed = discord.Embed(title=":x:Error:x:", colour=discord.Colour(0xf44242))
    coindata = requests.get("https://maplechange.com/api/v2/tickers/ccxbtc.json")
    btc = requests.get("https://www.bitstamp.net/api/ticker/")
    try:
        to_json = coindata.json()
    except ValueError:
        err_embed.description = "The MapleChange API is down"
        await client.say(embed = err_embed)
        return
    coindata_embed = discord.Embed(title="Conceal: MapleChange", url="https://maplechange.com/markets/ccxbtc", description="Current pricing of CCX", color=0x7F7FFF)
    coindata_embed.set_thumbnail(url=config['logo_url'])    
    url = 'https://maplechange.com/api/v2/tickers/ccxbtc.json'
    coindata_embed.add_field(name="Last", value="{0:,.0f} sats".format(round(float(coindata.json()['ticker']['last'])*100000000)), inline=True)
    coindata_embed.add_field(name="Buy", value="{0:,.0f} sats".format(round(float(coindata.json()['ticker']['buy'])*100000000)), inline=True)
    coindata_embed.add_field(name="Sell", value="{0:,.0f} sats".format(round(float(coindata.json()['ticker']['sell'])*100000000)), inline=True)

    coindata_embed.add_field(name="{}-USD".format(config['symbol']),
    value="${0:,.4f} USD".format(float(coindata.json()['ticker']['sell'])*float(btc.json()['last'])), inline=True)
    coindata_embed.add_field(name="BTC-USD", value="${0:,.2f} USD".format(float(btc.json()['last'])), inline=True)
    await client.say(embed=coindata_embed)
### NETWORK COMMANDS ###
@client.command()
async def hashrate():
    """ .hashrate - Returns network hashrate """
    data = daemon.getlastblockheader()
    hashrate = format_hash(float(data["block_header"]["difficulty"]) / 120)
    await client.say("The current global hashrate is **{}/s**".format(hashrate))

@client.command()
async def difficulty():
    """ .difficulty - Returns network difficulty """
    data = daemon.getlastblockheader()
    difficulty = float(data["block_header"]["difficulty"])
    await client.say("The current difficulty is **{0:,.0f}**".format(difficulty))


@client.command()
async def height():
    """ .height - Returns the current blockchain height """
    data = daemon.getlastblockheader()
    height = int(data["block_header"]["height"])
    await client.say("The current block height is **{:,}**".format(height))


@client.command()
async def supply():
    """ .supply - Returns the current circulating supply """
    supply = get_supply()
    await client.say("The current circulating supply is **{:0,.2f}** {}".format(supply, config['symbol']))

@client.command()
async def stats():
    """ .stats - Returns all network stats """
    data = daemon.getlastblockheader()
    hashrate = format_hash(float(data["block_header"]["difficulty"]) / 120)
    data = daemon.getlastblockheader()
    height = int(data["block_header"]["height"])
    deposits = int(data["block_header"]["deposits"]) / 1000000
    supply = get_supply()
    data = daemon.getlastblockheader()
    difficulty = float(data["block_header"]["difficulty"])
    stats_embed=discord.Embed(title="Conceal", url="https://github.com/TheCircleFoundation/", description="Complete Network Stats", color=0x7F7FFF)
    stats_embed.set_thumbnail(url=config['logo_url'])    
    hashFromPools = 0
    allPools = session2.query(pool).all()
    totalPools = len(allPools)
    for poolNumber in range(0,totalPools):        
        poolHash = allPools[poolNumber].hashrate
        hashFromPools = hashFromPools + poolHash
    stats_embed.add_field(name="Hashrate (from Pools)", value="{}KH/s".format(hashFromPools/1000))       
    stats_embed.add_field(name="Hashrate (from Difficulty)", value="{}/s".format(hashrate))
    stats_embed.add_field(name="Height", value="{:,}".format(height))
    stats_embed.add_field(name="Difficulty", value="{0:,.0f}".format(difficulty))
    stats_embed.add_field(name="Circulating Supply", value="{:0,.2f} CCX".format(supply))
    stats_embed.add_field(name="Deposits", value="{:0,.2f}".format(deposits))
    stats_embed.set_footer(text="Powered by the Conceal Discord bot. Message @katz for any issues.")
    await client.say(embed=stats_embed)


@client.command()
async def pools():
    """ .pools - Get a list of pools and current stats """
    stats_embed=discord.Embed(title="Conceal", url="https://github.com/TheCircleFoundation/", description="Mining Pool Stats", color=0x7F7FFF)
    stats_embed.set_thumbnail(url=config['logo_url'])    
    hashFromPools = 0
    allPools = session2.query(pool).all()
    totalPools = len(allPools)
    for poolNumber in range(0,totalPools):
        poolName = allPools[poolNumber].name
        poolSiteURL = allPools[poolNumber].poolurl
        poolHash = allPools[poolNumber].hashrate
        hashFromPools = hashFromPools + poolHash
        poolMiners = allPools[poolNumber].miners
        stats_embed.add_field(name=poolName, value=poolSiteURL, inline=False)
        stats_embed.add_field(name="Hashrate", value="{} KH/s".format(poolHash/1000))
        stats_embed.add_field(name="Miners", value="{:,}".format(poolMiners))     
    stats_embed.add_field(name="Hashrate (from Pools)", value="{}KH/s".format(hashFromPools/1000))           
    stats_embed.set_footer(text="Powered by the Conceal Discord bot. Message @katz for any issues.")
    await client.say(embed=stats_embed)


# WALLET COMMANDS ###
#@client.command(pass_context=True)
#async def members(ctx):
#    members = ""
#    allID = session.query(Wallet).all()
#    theID = 0
#    totalID = len(allID)
#    await client.say("List of members:")        
#    for theID in range(0,totalID):
#        currentID = allID[theID].userid
#        memberName = discord.utils.get(client.get_all_members(), id=str(currentID))
#        members = members + " @" + str(memberName)
#    await client.say(members)

@client.command(pass_context=True)
async def registerwallet(ctx, address):
    """ .registerwallet <addr> - Register your wallet in the database """

    err_embed = discord.Embed(title="Error", colour=discord.Colour(0xf44242))
    good_embed = discord.Embed(title="{}'s Wallet".format(ctx.message.author.name),colour=discord.Colour(0xD4AF37))
    if address is None:
        err_embed.description = "Please provide an address"
        await client.send_message(ctx.message.author, embed = err_embed)
        return

    exists = session.query(Wallet).filter(Wallet.userid == ctx.message.author.id).first()
    addr_exists = session.query(Wallet).filter(Wallet.address == address).first()
    if exists:
        good_embed.title = "Your wallet exists!".format(exists.address)
        good_embed.description = "```{}``` use `{}updatewallet <addr>` to change".format(exists.address, config['prefix'])
        await client.send_message(ctx.message.author, embed = good_embed)
        return
    if addr_exists:
        err_embed.description = "Address already registered by another user!"
        await client.send_message(ctx.message.author, embed = err_embed)
        return

    elif not exists and len(address) == 98:
        w = Wallet(address, ctx.message.author.id,ctx.message.id)
        session.add(w)
        session.commit()
        good_embed.title = "Successfully registered your wallet"
        good_embed.description = "```{}```".format(address)
        await client.send_message(ctx.message.author, embed = good_embed)
        pid = gen_paymentid(address)
        balance = session.query(TipJar).filter(TipJar.paymentid == pid).first()
        if not balance:
            t = TipJar(pid, ctx.message.author.id, 0)
            session.add(t)
        else:
            balance.paymentid = pid
        session.commit()
        tipjar_addr = "ccx7Wga6b232eSVfy8KQmBjho5TRXxX8rZ2zoCTyixfvEBQTj1g2Ysz1hZKxQtw874W3w6BZkMFSn5h3gUenQemZ2xiyyjxBR7"
        good_embed.title = "Your Tipjar Info"
        good_embed.description = "Deposit {} to start tipping! ```transfer 3 {} <amount> -p {}```".format(config['symbol'], tipjar_addr, pid)
        balance = session.query(TipJar).filter(TipJar.paymentid == pid).first()
        await client.send_message(ctx.message.author, embed = good_embed)
        return
    elif len(address) > 98:
        err_embed.description = "Your wallet must be 98 characeters long, your entry was too long"
    elif len(address) < 98:
        err_embed.description = "Your wallet must be 98 characeters long, your entry was too short"
    await client.say(embed = err_embed)

@registerwallet.error
async def registerwallet_error(error, ctx): 
    await client.say("Please provide an address: .registerwallet <addr>.")

@client.command(pass_context=True)
async def updatewallet(ctx, address):
    """ .updatewallet <addr> - Changes your registred wallet address """

    err_embed = discord.Embed(title="Error", colour=discord.Colour(0xf44242))

    if address == None:
        err_embed.description = "Please provide an address!"
        await client.send_message(ctx.message.author, embed=err_embed)
        return

    address = address.strip()
    good_embed = discord.Embed(title="{}'s Updated Wallet".format(ctx.message.author.name),colour=discord.Colour(0xD4AF37))
    exists = session.query(Wallet).filter(Wallet.userid == ctx.message.author.id).first()
    if not exists:
        err_embed.description = "You haven't registered a wallet!"

    addr_exists = session.query(Wallet).filter(Wallet.address == address).first()
    if addr_exists:
        err_embed.description = "Address already registered by another user!"
        await client.send_message(ctx.message.author, embed = err_embed)
        return
    elif exists and len(address) == 98:
        old_pid = gen_paymentid(exists.address)
        old_balance = session.query(TipJar).filter(TipJar.paymentid == old_pid).first()
        exists.address = address
        pid = gen_paymentid(address)
        old_balance.paymentid = pid
        good_embed.title = "Successfully updated your wallet"
        good_embed.description = "```{}```".format(address)
        session.commit()
        await client.send_message(ctx.message.author, embed = good_embed)

        tipjar_addr = "ccx7Wga6b232eSVfy8KQmBjho5TRXxX8rZ2zoCTyixfvEBQTj1g2Ysz1hZKxQtw874W3w6BZkMFSn5h3gUenQemZ2xiyyjxBR7"
        good_embed.title = "Your Tipjar Info"
        good_embed.description = "Deposit {} to start tipping! ```transfer 3 {} <amount> -p {}```".format(config['symbol'], tipjar_addr, pid)
        await client.send_message(ctx.message.author, embed = good_embed)

        good_embed.title = "Balance Update"
        good_embed.url = ""
        good_embed.description = "New Balance: `{:0,.2f}` {1}".format(old_balance.amount / config['units'], config['symbol'])
        await client.send_message(ctx.message.author, embed = good_embed)
        return
    elif len(address) > 98:
        err_embed.description = "Your wallet must be 98 characeters long, your entry was too long"
    elif len(address) < 98:
        err_embed.description = "Your wallet must be 98 characeters long, your entry was too short"
    await client.say(embed=err_embed)

@updatewallet.error
async def updatewallet_error(error, ctx): 
    await client.say("Please provide an address: .updatewallet <addr>")

@client.command(pass_context=True)
async def wallet(ctx, user: discord.User=None):
    """ .wallet - Returns your registered wallet address """

    err_embed = discord.Embed(title=":x:Error:x:", colour=discord.Colour(0xf44242))
    good_embed = discord.Embed(colour=discord.Colour(0xD4AF37))
    if not user:
        exists = session.query(Wallet).filter(Wallet.userid == ctx.message.author.id).first()
        if not exists:
            err_embed.description = "You haven't registered a wallet or specified a user!"
        else:
            good_embed.title = "Your wallet"
            good_embed.description = "Here's your wallet {}! ```{}```".format(ctx.message.author.mention, exists.address)
            await client.send_message(ctx.message.author, embed = good_embed)
            return
    else:
        exists = session.query(Wallet).filter(Wallet.userid == user.id).first()
        if not exists:
            err_embed.description = "{} hasn't registered a wallet!".format(user.name)
        else:
            good_embed.title = "{}'s wallet".format(user.name)
            good_embed.description = "```{}```".format(exists.address)
            await client.send_message(ctx.message.author, embed = good_embed)
            return
    await client.send_message(ctx.message.author, embed = err_embed)


@client.command(pass_context=True)
async def deposit(ctx, user: discord.User=None):
    """ .deposit - Get deposit information so you can start tipping """
    err_embed = discord.Embed(title=":x:Error:x:", colour=discord.Colour(0xf44242))
    good_embed = discord.Embed(title="Your Tipjar Info")
    tipjar_addr = "ccx7Wga6b232eSVfy8KQmBjho5TRXxX8rZ2zoCTyixfvEBQTj1g2Ysz1hZKxQtw874W3w6BZkMFSn5h3gUenQemZ2xiyyjxBR7"
    exists = session.query(Wallet).filter(Wallet.userid == ctx.message.author.id).first()
    if exists:
        pid = gen_paymentid(exists.address)
        good_embed.description = "Deposit {} to start tipping! ,Send the funds you want to deposit to the address: ``{}`` (Pay to: in the GUI) and put ``{}`` in the Payment ID field. CLI users just send a transfer to the same address and payment ID.".format(config['symbol'], tipjar_addr, pid)
        balance = session.query(TipJar).filter(TipJar.paymentid == pid).first()
        if not balance:
            t = TipJar(pid, ctx.message.author.id, 0)
            session.add(t)
            session.commit()
        await client.send_message(ctx.message.author, embed = good_embed)
    else:
        err_embed.description = "You haven't registered a wallet!"
        err_embed.add_field(name="Help", value="Use `{}registerwallet <addr>` before trying to tip!".format(config['prefix']))
        await client.say(embed=err_embed)


@client.command(pass_context=True)
async def balance(ctx, user: discord.User=None):
    """ .balance - PMs your tipjar balance """
    err_embed = discord.Embed(title=":x:Error:x:", colour=discord.Colour(0xf44242))
    good_embed = discord.Embed(title="Your Tipjar Balance is")
    exists = session.query(Wallet).filter(Wallet.userid == ctx.message.author.id).first()
    if exists:
        pid = gen_paymentid(exists.address)
        balance = session.query(TipJar).filter(TipJar.paymentid == pid).first()
        if not balance:
            t = TipJar(pid, ctx.message.author.id, 0)
            session.add(t)
            session.commit()
        else:
            good_embed.description = "`{0:,.2f}` {1}".format(balance.amount / config['units'], config['symbol'])
            good_embed.add_field(name="Widthrawal", value="You can tip yourself to widthraw CCX to your wallet")
            await client.send_message(ctx.message.author, embed=good_embed)
    else:
        err_embed.description = "You haven't registered a wallet!"
        err_embed.add_field(name="Help", value="Use `{}registerwallet <addr>` before trying to tip!".format(config['prefix']))
        await client.say(embed=err_embed)


EMOJI_MONEYBAGS = "\U0001F4B8"
EMOJI_SOS = "\U0001F198"
EMOJI_ERROR = "\u274C"


@client.command(pass_context=True)
async def tip(ctx, amount, sender):
    """ .tip <amount> <username> - Tips a user the specified amount """
    await _tip(ctx, amount, None, None)


async def _tip(ctx, amount,
               sender: discord.User=None,
               receiver: discord.User=None):

    err_embed = discord.Embed(title=":x:Error:x:", colour=discord.Colour(0xf44242))
    good_embed = discord.Embed(title="You were tipped!", colour=discord.Colour(0xD4AF37))
    request_desc = "Register with `{}registerwallet <youraddress>` to get started!".format(config['prefix'])
    request_embed = discord.Embed(title="{} wants to tip you".format(ctx.message.author.name), description=request_desc)

    if not sender:  # regular tip
        sender = ctx.message.author

    if not receiver:
        tipees = ctx.message.mentions
    else:
        tipees = [receiver, ]

    try:
        amount = int(round(float(amount)*config['units']))
    except:
        await client.say("Amount must be a number equal or greater than {}".format(10000 / config['units']))
        return False

    if amount <= 9999:
        err_embed.description = "`amount` must be equal or greater than {}".format(10000 / config['units'])
        await client.say(embed=err_embed)
        return False

    fee = get_fee(amount)
    self_exists = session.query(Wallet).filter(Wallet.userid == sender.id).first()

    if not self_exists:
        err_embed.description = "You haven't registered a wallet!"
        err_embed.add_field(name="Help", value="Use `{}registerwallet <addr>` before trying to tip!".format(config['prefix']))
        await client.send_message(sender, embed=err_embed)
        return False

    pid = gen_paymentid(self_exists.address)
    balance = session.query(TipJar).filter(TipJar.paymentid == pid).first()
    if not balance:
        t = TipJar(pid, sender.id, 0)
        session.add(t)
        session.commit()
        err_embed.description = "You are not registered, please `{}deposit` to tip".format(config['prefix'])
        await client.send_message(sender, embed=err_embed)
        return False

    if balance.amount < 0:
        balance.amount = 0
        session.commit()
        err_embed.description = "Your balance was negative!"
        await client.send_message(sender, embed=err_embed)

        katz = discord.utils.get(client.get_all_members(), id='408875878328827916')
        err_embed.title = "{} had a negative balance!!".format(sender.name)
        err_embed.description = "PID: {}".format(pid)

        await client.send_message(katz, embed=err_embed)
        return False

    if ((len(tipees)*(amount))+fee) > balance.amount:
        err_embed.description = "Your balance is too low! Amount + Fee = `{}` {}".format(((len(tipees)*(amount))+fee) / config['units'], config['symbol'])
        await client.add_reaction(ctx.message, "\u274C")
        await client.send_message(sender, embed=err_embed)
        return False

    destinations = []
    actual_users = []
    failed = 0
    for user in tipees:
        user_exists = session.query(Wallet).filter(Wallet.userid == user.id).first()
        if user_exists:
            destinations.append({'amount': amount, 'address': user_exists.address})
            if user_exists.userid != sender.id:  # multitip shouldn't tip self.
                actual_users.append(user)
        else:
            failed = failed+1

            await client.add_reaction(ctx.message, EMOJI_SOS)
            try:
                await client.send_message(user, embed = request_embed)
            except:
                continue


    if len(destinations) == 0:
        await client.add_reaction(ctx.message, EMOJI_SOS)
        return False

    transfer = build_transfer(amount, destinations, balance)
    print(transfer)
    result = rpc.transfer(transfer)
    print(result)

    await client.add_reaction(ctx.message, EMOJI_MONEYBAGS)

    balance.amount -= ((len(actual_users)*amount)+fee)
    tx = Transaction(result['tx_hash'], (len(actual_users)*amount)+fee, balance.paymentid)
    session.add(tx)
    session.commit()
    good_embed.title = "Tip Sent!"
    good_embed.description = (
        "Sent `{0:,.2f}` {1} to {2} users! With Transaction Hash ```{3}```"
        .format(amount / config['units'],
                config['symbol'],
                len(actual_users),
                result['tx_hash']))
    good_embed.url = (
        "http://www.example.com/#?hash={}#blockchain_transaction"
        .format(result['tx_hash']))
    good_embed.add_field(name="New Balance", value="`{:0,.2f}` {}".format(balance.amount / config['units'], config['symbol']))
    good_embed.add_field(name="Transfer Info", value="Successfully sent to {0} users. {1} failed.".format(len(actual_users), failed))
    try:
        await client.send_message(sender, embed=good_embed)
    except:
        pass
    for user in actual_users:
        good_embed = discord.Embed(title="You were tipped!", colour=discord.Colour(0xD4AF37))
        good_embed.description = (
            "{0} sent you `{1:,.2f}` {2} with Transaction Hash ```{3}```"
            .format(sender.mention,
                    amount / config['units'],
                    config['symbol'],
                    result['tx_hash']))
        good_embed.url = (
            "http://www.example.com/#?hash={}#blockchain_transaction"
            .format(result['tx_hash']))
        try:
            await client.send_message(user, embed=good_embed)
        except:
            continue
    return True



client.run(config['token'])
