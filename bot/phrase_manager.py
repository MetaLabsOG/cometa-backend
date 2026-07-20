import random


class Phrases:
    @classmethod
    def greet(cls) -> str:
        return random.choice(
            [
                "Hey, beautiful!❤",
                "Hey, what's up?)",
                "How you doing?😏",
                "What a great day, huh?)",
                "Bip-bop! Beep, bop!🤖",
            ]
        )

    @classmethod
    def check_pools(cls) -> str:
        return random.choice(
            [
                "Let's see what you have😏",
                "Are you farming hard? Let's find out!",
                "So, what do we have here...",
                "Farming hard, huh?",
            ]
        )
