from enum import Enum


class ContractType(str, Enum):
    FARM = 'farm'
    DISTRIBUTION = 'distribution'
