NAME = "idle"


class Bot:
    def __init__(self, hello):
        self.slot = hello["slot"]

    def act(self, obs):
        return {"tick": obs["tick"]}

    def end(self, msg):
        pass
