from discord.ext import commands

from bot.env import settings

client = commands.Bot(command_prefix='!')
# TODO: add DiscordComponents


@client.event
async def on_ready():
    print("I'm Ready!")


client.run(settings.discord_api_token)
