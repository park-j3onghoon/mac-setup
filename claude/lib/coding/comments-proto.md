# Comments and docstrings: proto

- Comment scope: write only shape and signatures in proto files; put contract, validation and rationale in server code, the PR body and Linear. Comment a structure that looks like a mistake (an intentionally empty `Foo {}`) until a field arrives, and name in a comment the organization that currently fills a role-neutral field (`string manager_name = 6;  // 담당 BD`).
