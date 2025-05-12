import yaml


def load_config_file(file:str) -> dict:
    with open(file) as f:
        config_file = yaml.safe_load(f)
    
    return config_file
