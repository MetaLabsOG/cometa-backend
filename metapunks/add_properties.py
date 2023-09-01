import json

DEFAULT_DANCE = 'Graciously Standing'

dances = {
    37: 'Snake Hip Hop',
    3: 'Pro Hip Hop Flex',
    4: 'Hip Hop',
    19: 'Swing',
    23: 'Swing',
    31: 'Shopping Cart Flex',
    34: 'Pro Hip Hop Flex',
    41: 'Samba',
    45: 'Hip Hop Body',
    49: 'Samba'
}

SOURCE_DIR = '/Users/nikitagorokhov/YBG/first_batch'


if __name__ == '__main__':
    for i in range(2, 51):
        with open(f'{SOURCE_DIR}/attrs_{i}.json') as attr_file:
            attr_json = json.load(attr_file)
            dance_name = dances.get(i, DEFAULT_DANCE)
            attr_json.append({
                'trait_type': 'AR Dance',
                'value': dance_name
            })
            with open(f'{SOURCE_DIR}/attrs_{i}.json', 'w') as out_file:
                json.dump(attr_json, out_file)
            print(f'Added dance {dance_name} to {i}')
