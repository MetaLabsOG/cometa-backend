import random


class Phrases:
    @classmethod
    def greet(cls) -> str:
        return random.choice([
            'Hey, beautiful!❤',
            'Hey, what\'s up?)',
            'How you doing?😏',
            'What a great day, huh?)',
            'Bip-bop! Beep, bop!🤖'
        ])
