from discord.ext import commands
from discord_components import DiscordComponents

from env import settings

client = commands.Bot(command_prefix='!')
DiscordComponents(client)


@client.event
async def on_ready():
    print("I'm Ready!")


client.run(settings.discord_api_token)
