from discord.ext import commands

from bot.env import bot_settings

client = commands.Bot(command_prefix='!')
# TODO: add DiscordComponents


@client.event
async def on_ready():
    print("I'm Ready!")


client.run(bot_settings.discord_api_token)
