import discord
import re
import asyncio
import traceback
from discord.ext import commands
from datetime import datetime, timedelta
from utils import permissions, utils, dataIO

# parts of code took from https://github.com/Rapptz/RoboDanny
# possible to handle some errors here?
# todo case insensitive converter
# todo hierarchy on role command
# todo moderation commands: {add here}


class MemberID(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            m = await commands.MemberConverter().convert(ctx, argument)
        except commands.BadArgument:
            try:
                return int(argument, base=10)
            except ValueError:
                raise commands.BadArgument(f"{argument} is not a valid member or member ID.") from None
        else:
            return m.id


class RoleID(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            r = await commands.RoleConverter().convert(ctx, argument)
        except commands.BadArgument:
            try:
                return int(argument, base=10)
            except ValueError:
                raise commands.BadArgument(f"{argument} is not a valid role or Role ID.") from None
        else:
            return r.id


class ActionReason(commands.Converter):
    async def convert(self, ctx, argument):
        ret = argument

        if len(ret) > 512:
            reason_max = 512 - len(ret) - len(argument)
            raise commands.BadArgument(f'reason is too long ({len(argument)}/{reason_max})')
        return ret


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = dataIO.get_Info("config.json")

    async def check_status(self, ctx, member, reason:str = None):
        user = self.bot.ww.dbh.get_alarmed_user_by_id(member.id)

        if user is None or member is None:
            raise Exception(f'error while trying to warn the user\nTry again using ID')
        
        try:
            if user["strikes"] == 1:
                await self.bot.log_channel.send(f'```❗{member.name} HAS BEEN WARNED ONCE```')
                await self.unmute(ctx, member=member, no_action_message=True)
                await ctx.send(utils.actionmessage("warned"))
                try:
                    if reason is None or len(reason) < 1:
                        await member.send('This is the first time that you get warned, next time you\'ll be muted')
                    else:
                        await member.send("WARN:\n" + reason)
                except (discord.HTTPException, discord.Forbidden):
                    await ctx.send("Could not send DM to user, but warning was applied")

            if user["strikes"] == 2:
                await self.bot.log_channel.send(f'```❗{member.name} HAS BEEN WARNED TWICE```')
                await ctx.send(utils.actionmessage("warned"))
                await self.mute(ctx, member=member, time=str(5), reason=reason or "warned 2 times", no_action_message=True)
                try:
                    if reason is None or len(reason) < 1:
                        await member.send('This is the second time that you get warned, you\'ll be muted for 5 hours.\n'
                                        'next time you may be **banned!!** for ever. ')
                    else:
                        await member.send("WARN:\n" + reason)
                except (discord.HTTPException, discord.Forbidden):
                    await ctx.send("Could not send DM to user, but warning and mute were applied")

            if user["strikes"] == 3:
                await self.bot.log_channel.send(f'```❗{member.name} HAS BEEN WARNED 3 TIMES```')
                await self.ban(ctx, member=member.id, reason=reason or "warned 3 times", no_action_message=True)
                await ctx.send(utils.actionmessage("warned"))
                try:
                    if reason is None or len(reason) < 1:
                        await member.send('This is the third time that you get warned, you are banned from the server\n'
                                        'the mods will talk about that.')
                    else:
                        await member.send("WARN:\n" + reason)
                except (discord.HTTPException, discord.Forbidden):
                    await ctx.send("Could not send DM to user, but warning and ban were applied")

        except discord.Forbidden:
            raise Exception(f'I don\'t have permission to ban {member.nick if member.nick is not None else member.name}')
        except Exception as e:
            print(''.join(traceback.format_tb(e.__traceback__)))
            print(f"Error: {str(e)}")
            raise Exception(f'There was an error while trying to warn the user\nThe user may have been warned anyway. Please check the logs.')
            

    @commands.command(
        name='warn',
        help='Warns a member',
        description='The warn command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def _warn(self, ctx, member: discord.Member, *, reason: str = None):
        if await permissions.check_priv(ctx, member):
            return
        try:
            strikes = self.bot.ww.dbh.get_alarmed_user_by_id(member.id)
            if strikes is not None and strikes["strikes"] > 2:
                return await ctx.send(f"The memeber is warned {strikes['strikes'] if strikes is not None else 3} times, you can\'t {ctx.command.name} him")
            else:
                if strikes is not None and strikes["strikes"] == 2 and any(role.id in self.config.lilmoderator_roles for role in ctx.author.roles):
                    return await ctx.send("As a Sub Mod you can\'t warn the user 3 times!")
                self.bot.ww.dbh.alarm_user_by_id(member.id)
                await self.check_status(ctx, member, reason=reason)
        except Exception as e:
            await ctx.send(str(e))
        #else:
            #await ctx.send(utils.actionmessage("warned"))

    @commands.command(
        name='unwarn',
        help='Unwarns a member',
        description='The unwarn command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def _unwarn(self, ctx, *, member: discord.Member):
        if await permissions.check_priv(ctx, member):
            return
        try:
            strikes = self.bot.ww.dbh.get_alarmed_user_by_id(member.id)
            if strikes is None:
                return await ctx.send(f"The memeber is warned 0 times, you can\'t {ctx.command.name} him")
            else:
                self.bot.ww.dbh.unalarm_user_by_id(member.id)
                await ctx.send(utils.actionmessage("unwarned"))
        except Exception as e:
            print(e)
            await ctx.send(f'I don\'t have permission to {ctx.command} {member.nick if member.nick is not None else member.display_name}')

    @commands.command(
        name='warnedmembers',
        help='Returns the warned members',
        description='The warnedmembers command!',
        aliases=['wmembers', 'wusers', 'warnedusers']
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def _warned_users(self, ctx):
        warned_users = self.bot.ww.dbh.get_alarmed_users()
        loop = [f'{user["name"]} ({user["_id"]}) <=> {user["strikes"]}' for user in warned_users]
        await utils.prettyResults(
            ctx, "name", f"Found **{len(loop)}** members", loop
        )

    @commands.command(
        name='iswarned',
        help='Checks if the member is warned',
        description='The iswarned command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def _is_alarmed(self, ctx, *, member: discord.Member):
        user = self.bot.ww.dbh.get_alarmed_user_by_id(member.id)
        if user is None:
            return await ctx.send('The member has never been warned')

        await ctx.send(f'Yes, {member.nick if member.nick is not None else member.name} has been warned **{user["strikes"]}** times')

    @commands.command(
        name='kick',
        help='Kicks a member.',
        description='The kick command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_mod()
    async def kick(self, ctx, member: discord.Member, *, reason: str = None):
        if await permissions.check_priv(ctx, member):
            return
        try:
            await member.kick(reason=utils.responsible(ctx.author, reason))
            await ctx.send(utils.actionmessage("kicked"))
        except Exception as e:
            print(e)
            await ctx.send(f'I don\'t have permission to {ctx.command} {member.nick if member.nick is not None else member.display_name}')

    @commands.command(
        name='nickname',
        help=' Nicknames a member from the current server.',
        description='The nickname command!',
        aliases=["nick"]
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def nickname(self, ctx, member: discord.Member, *, name: str = None):
        if await permissions.check_priv(ctx, member):
            return

        try:
            await member.edit(nick=name, reason=utils.responsible(ctx.author, "Changed by command"))
            message = f"Changed **{member.name}'s** nickname to **{name}**"
            if name is None:
                message = f"Reset **{member.name}'s** nickname"
            await ctx.send(message)
        except Exception as e:
            print(e)
            await ctx.send(
                f'I don\'t have permission to {ctx.command} {member.nick if member.nick is not None else member.display_name}')
    
    @commands.command(
        name='ban',
        help=' Bans a member. !all his messages wil be cancelled',
        description='The ban command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_mod()
    async def ban(self, ctx, member: MemberID, *, reason: str = None, no_action_message:bool = False):
        m = ctx.guild.get_member(member)

        if m is None:
            await ctx.send(f'{member} not found')

        if await permissions.check_priv(ctx, m):
            return

        try:
            await m.ban(reason=utils.responsible(ctx.author, reason))
            if not no_action_message:
                await ctx.send(utils.actionmessage("banned"))
        except Exception as e:
            print(e)
            await ctx.send(f'I don\'t have permission to {ctx.command} {member}')

    @commands.command(
        name='unban',
        help=' Unbans a member. !you **MUST** use the member\'s ID',
        description='The unban command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_mod()
    async def unban(self, ctx, member: MemberID, *, reason: str = None, no_action_message:bool = False):
        try:
            await ctx.guild.unban(discord.Object(id=member), reason=utils.responsible(ctx.author, reason))
            if not no_action_message:
                await ctx.send(utils.actionmessage("unbanned"))
        except Exception as e:
            print(e)
            await ctx.send(f'I don\'t have permission to {ctx.command} {member}')

    '''@unban.error
        async def unban_error(self, ctx, error):
            if isinstance(error, errors.BadArgument) or isinstance(error, errors.MissingRequiredArgument):
                await ctx.send(
                    f'use id'
                )
    '''
         
    @commands.command(
        name='softban',
        help=' Softbans a member. !you **MUST** use the member\'s ID',
        description='The softban command!',
        aliases=['sfban']
    )
    @commands.guild_only()
    @permissions.is_mod()
    async def softban(self, ctx, member: MemberID, *, reason: str = None, no_action_message:bool = False):
        try:
            await ctx.guild.ban(discord.Object(id=member), reason=utils.responsible(ctx.author, reason))
            if not no_action_message:
                await ctx.send(utils.actionmessage("banned"))
            await ctx.guild.unban(discord.Object(id=member), reason=utils.responsible(ctx.author, reason))
            if not no_action_message:
                await ctx.send(utils.actionmessage("unbanned"))
        except Exception as e:
            print(e)
            await ctx.send(f'I don\'t have permission to {ctx.command} {member}')

    @commands.command(
        name='mute',
        help='Mutes a user, he won\'t be able to write until you unmute him',
        description='The mute command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def mute(self, ctx, member: discord.Member, time: str = None, *, reason: str = None, no_action_message: bool = False):
        if await permissions.check_priv(ctx, member):
            return

        if time is not None and not time.isdigit():
            return await ctx.send(f"{time} is not a valid value")

        try:
            await member.timeout(timedelta(hours=int(time)), reason=utils.responsible(ctx.author, reason))

            if not no_action_message:
                await ctx.send(utils.actionmessage("muted", time=time))
        except Exception as e:
            print(e)
            await ctx.send(f'I don\'t have permission to {ctx.command} {member.nick if member.nick is not None else member.display_name}')

    @commands.command(
        name='unmute',
        help='unmutes a user, if he was muted, now he can write',
        description='The unmute command!',
        aliases=[]
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def unmute(self, ctx, member: discord.Member, *, reason: str = None, no_action_message: bool = False):
        if await permissions.check_priv(ctx, member):
            return

        try:
            await member.timeout(None, reason=utils.responsible(ctx.author, reason))

            if not no_action_message:
                await ctx.send(utils.actionmessage("unmuted"))
        except Exception as e:
            print(e)
            await ctx.send(
                f'I don\'t have permission to {ctx.command} {member.nick if member.nick is not None else member.display_name}'
            )

    @commands.group(
        name='find',
        help='Finds a user within your search conditions',
        description='The find role command!',
        aliases=[],
    )
    @permissions.is_lil_mod()
    async def find(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.channel.send(f'you haven\'t specified the argument! type {ctx.prefix}help {ctx.command.name}')

    @find.command(
        name='playing',
        help='<game> - text of the Game !case sensitive',
        description='finds a member that is playing a specified game',
        aliases=[],
    )
    async def find_playing(self, ctx, *, search: str):
        loop = []
        for i in ctx.guild.members:
            if i.activities and (not i.bot):
                for g in i.activities:
                    if g.name and (search.lower() in g.name.lower()):
                        loop.append(f"{i} | {type(g).__name__}: {g.name} ({i.id})")

        await utils.prettyResults(
            ctx, "playing", f"Found **{len(loop)}** on your search for **{search}**", loop
        )

    @find.command(
        name='username',
        help='<username> - username of the member !case sensitive',
        description='finds a member with the specified username',
        aliases=['name', 'user'],
    )
    async def find_name(self, ctx, *, search: str):
        loop = [f"{i} ({i.id})" for i in ctx.guild.members if search.lower() in i.name.lower() and not i.bot]
        await utils.prettyResults(
            ctx, "name", f"Found **{len(loop)}** on your search for **{search}**", loop
        )

    @find.command(
        name='nickname',
        help='<nickname> - nickname of the member !case sensitive',
        description='finds a member with the specified nickname',
        aliases=['nick'],
    )
    async def find_nickname(self, ctx, *, search: str):
        loop = [f"{i.nick} | {i} ({i.id})" for i in ctx.guild.members if i.nick if
                (search.lower() in i.nick.lower()) and not i.bot]
        await utils.prettyResults(
            ctx, "name", f"Found **{len(loop)}** on your search for **{search}**", loop
        )

    @find.command(
        name='id',
        help='<id> - id of the member',
        description='finds a member with the specified id',
        aliases=[]
    )
    async def find_id(self, ctx, *, search: int):
        loop = [f"{i} | {i} ({i.id})" for i in ctx.guild.members if (str(search) in str(i.id)) and not i.bot]
        await utils.prettyResults(
            ctx, "name", f"Found **{len(loop)}** on your search for **{search}**", loop
        )

    @find.command(
        name='tag',
        help='<tag> - the tag of the member - the #1234 after his name',
        description='finds a member with the specified tag',
        aliases=[]
    )
    async def find_tag(self, ctx, *, search: str):
        if not len(search) == 4 or not re.compile("^[0-9]*$").search(search):
            return await ctx.send("You must provide exactly 4 digits")

        loop = [f"{i} ({i.id})" for i in ctx.guild.members if search == i.discriminator]
        await utils.prettyResults(
            ctx, "discriminator", f"Found **{len(loop)}** on your search for **{search}**", loop
        )
    
    
    @commands.group(
        name='reset',
        help='resets videos and tweets in the db',
        description='The reset command!',
        aliases=['res'],
    )
    @commands.guild_only()
    @permissions.is_mod()
    async def reset(self, ctx):
        if ctx.invoked_subcommand is None:
            await self.bot.ww.reset(type='soft')

    @reset.command(
        name='videos',
        help='resets only videos',
        description='',
        aliases=[]
    )
    async def _reset_videos(self, ctx):
        await self.bot.ww.reset(name='videos', type='soft')

    @reset.command(
        name='tweets',
        help='resets only tweets',
        description='',
        aliases=[]
    )
    async def _reset_tweets(self, ctx):
        await self.bot.ww.reset(name='tweets', type='soft')

    @commands.group(
        name='fullreset',
        help='removes and readd videos in the database',
        description='The full reset command!',
        aliases=['fres', 'fullres'],
    )
    @commands.guild_only()
    @permissions.is_mod()
    async def full_reset(self, ctx):
        if ctx.invoked_subcommand is None:
            await self.bot.ww.reset(type='full')

    @full_reset.command(
        name='videos',
        help='removes and readd only videos',
        description='',
        aliases=[]
    )
    async def _full_reset_videos(self, ctx):
        await self.bot.ww.reset('videos', type='full')

    @full_reset.command(
        name='tweets',
        help='removes and readd only tweets (currently useless)',
        description='',
        aliases=[]
    )
    async def _full_reset_tweets(self, ctx):
        await self.bot.ww.reset(name='tweets', type='full')
     
    @commands.group(
        name='clear',
        help='Removes messages within your conditions',
        description='The clear command!',
        aliases=['cl', 'delet'],
    )
    @commands.guild_only()
    @permissions.is_lil_mod()
    async def clear(self, ctx):
        if ctx.invoked_subcommand is None:
            if ctx.subcommand_passed is None:
                await ctx.channel.send(f'you haven\'t specified the argument! type {ctx.prefix}help {ctx.command.name}')
            else:
                try:
                    await self.do_removal(ctx, int(ctx.subcommand_passed), lambda e: True)
                except:
                    await ctx.send('Invalid amount')

    async def do_removal(self, ctx, limit, predicate, *, before=None, after=None, message=True):
        if limit > 2000:
            return await ctx.send(f'Too many messages to search given ({limit}/2000)')

        if before is None:
            before = ctx.message
        else:
            before = discord.Object(id=before)

        if after is not None:
            after = discord.Object(id=after)

        try:
            deleted = await ctx.channel.purge(limit=limit, before=before, after=after, check=predicate)
        except discord.Forbidden:
            return await ctx.send('I do not have permissions to delete messages.')
        except discord.HTTPException as e:
            return print(e)  # await ctx.send(f'Error: {e} (try a smaller search?)')

        deleted = len(deleted)
        if message is True:
            try:
                m = await ctx.send("https://media.tenor.co/videos/6f2052aeba7c1736ab73d681ebd73ab7/mp4")
                await asyncio.sleep(4)
                await m.delete()
            except:
                pass

    @clear.command(
        name='all',
        help='<amount> - default value is 100',
        description='Removes all messages.',
        aliases=[]
    )
    async def _remove_all(self, ctx, search=100):
        await self.do_removal(ctx, search, lambda e: True)

    @clear.command(
        name='files',
        help='<amount> - default value is 100',
        description='Removes all messages with attachments.',
        aliases=[]
    )
    async def _remove_files(self, ctx, search=100):
        await self.do_removal(ctx, search, lambda e: len(e.attachments))

    @clear.command(
        name='mentions',
        help='<amount> - default value is 100',
        description='Removes all messages with mentions.',
        aliases=[]
    )
    async def _remove_mentions(self, ctx, search=100):
        await self.do_removal(ctx, search, lambda e: len(e.mentions) or len(e.role_mentions))

    @clear.command(
        name='images',
        help='<amount> - default value is 100',
        description='Removes all messages with embeds or images.',
        aliases=[]
    )
    async def _remove_images(self, ctx, search=100):
        await self.do_removal(ctx, search, lambda e: len(e.embeds) or len(e.attachments))

    @clear.command(
        name='member',
        help='<amount> - default value is 100',
        description='Removes all messages snet by the member.',
        aliases=[]
    )
    async def _remove_member(self, ctx, member: discord.Member, search=100):
        await self.do_removal(ctx, search, lambda e: e.author == member)

    @clear.command(
        name='contains',
        help='<text>, must be at least 3 characters',
        description='Removes all messages containing <text>',
        aliases=[]
    )
    async def _remove_contains(self, ctx, *, substr: str):
        if len(substr) < 3:
            await ctx.send('The substring length must be at least 3 characters.')
        else:
            await self.do_removal(ctx, 100, lambda e: substr in e.content)

    @clear.command(
        name='bots',
        help='<amount> <prefix> - default values are 100, this bot\'s prefix',
        description='Removes all messages sent by a bot',
        aliases=[]
    )
    async def _remove_bots(self, ctx, search=100, prefix=None):
        getprefix = prefix if prefix else self.config.prefix

        def predicate(m):
            return (m.webhook_id is None and m.author.bot) or m.content.startswith(tuple(getprefix))

        await self.do_removal(ctx, search, predicate)

    @clear.command(
        name='users',
        help='<amount> - default value is 100',
        description='Removes all messages sent by users, so it s won\'t delete bot\'s messages',
        aliases=[]
    )
    async def _remove_users(self, ctx, search=100):

        def predicate(m):
            return m.author.bot is False

        await self.do_removal(ctx, search, predicate)

    @clear.command(
        name='reactions',
        help=f'<amount> - default value is 100',
        description='Removes all reactions from messages',
        aliases=[]
    )
    async def _remove_reactions(self, ctx, search=100):

        if search > 2000:
            return await ctx.send(f'Too many messages to search for ({search}/2000)')

        total_reactions = 0
        async for message in ctx.history(limit=search, before=ctx.message):
            if len(message.reactions):
                total_reactions += sum(r.count for r in message.reactions)
                await message.clear_reactions()
        try:
            m = await ctx.send(f'Successfully removed {total_reactions} reactions.')
            await asyncio.sleep(4)
            await m.delete()
        except:
            pass
    
    
    @commands.command(
        name='pickaquestion',
        help='Picks a question, resets the timer',
        description='The pickaquestion command',
        aliases=['paq'],
    )
    @permissions.is_mod()
    async def _pickaquestion(self, ctx):
        await self.bot.iw.send_question()


    @commands.command(  # move this up
        name='role',
        help='roles a member',
        description='the role command!',
        aliases=[]
    )
    @permissions.is_lil_mod()
    async def _role(self, ctx, member: MemberID, *, role: RoleID):

        if role in (742318951182368829, 684039437482590229, 742319636439105537, 684797230758363137, 703187683429842985):
            return await ctx.send('What are you trying to do monkaS')

        selected_role = ctx.guild.get_role(role)
        selected_member = ctx.guild.get_member(member)

        if not selected_role:
            return await ctx.send(f"Could not find any role matching **{role}**")

        if not selected_member:
            return await ctx.send(f"Could not find any member matching **{member}**")

        try:
            await selected_member.add_roles(selected_role)
        except Exception as e:
            print(e)

    @commands.command(  # move this up
        name='unrole',
        help='unroles a member',
        description='the unrole command!',
        aliases=[]
    )
    @permissions.is_mod()
    async def _unrole(self, ctx, member: MemberID, *, role: RoleID):

        if role in (742318951182368829, 684039437482590229, 742319636439105537, 684797230758363137, 703187683429842985):
            return await ctx.send('What are you trying to do monkaS')

        selected_role = ctx.guild.get_role(role)
        selected_member = ctx.guild.get_member(member)

        if not selected_role:
            return await ctx.send(f"Could not find any role matching **{role}**")

        if not selected_member:
            return await ctx.send(f"Could not find any member matching **{member}**")

        try:
            await selected_member.remove_roles(selected_role)
        except Exception as e:
            print(e)
            
    
    @commands.command(
        name='nicknamesof',
        help='list the previous nicknames of an user',
        description='the nick command!',
        aliases=["prevnicks", "nicksof"]
    )
    @permissions.is_lil_mod()
    async def _nicknamesof(self, ctx, member: MemberID):
        try:
            nicknames = self.bot.ww.dbh.get_user_nicknames_by_id(member)
            
            if not nicknames: 
                raise Exception()
            
            await utils.prettyResults(
                ctx, "nicknames", f"Found **{len(nicknames)}** results", nicknames
            )
        except Exception as e:
            print(e)
            await ctx.send("No records found")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
