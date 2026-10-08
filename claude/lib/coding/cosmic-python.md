On a conflict, the other coding rules and the project's existing code win over this file. The sections follow Architecture Patterns with Python (Harry Percival and Bob Gregory); replace the book's example domain (`allocation`, `Product`, `Batch`, `OrderLine`, `sku`) with the project's.

## Project layout

- Package: put all app code in one installable package `src/allocation/` (minimal `setup.py`, `pip install -e`) and keep `tests/` next to `src/`.
- Domain: keep entities, value objects, aggregates, domain services and domain exceptions in `domain/model.py`, and message dataclasses in `domain/commands.py` and `domain/events.py`.
- Service layer: keep use-case functions, `EVENT_HANDLERS`, `COMMAND_HANDLERS` and service exceptions such as `InvalidSku` in `service_layer/handlers.py`, next to `unit_of_work.py` and `messagebus.py`.
- Adapters: put driven adapters for outbound I/O in `adapters/` (`orm.py`, `repository.py`, `notifications.py`, `redis_eventpublisher.py`) and keep each abstract port in the same file as its implementations.
- Entrypoints: put driving adapters in `entrypoints/` (`flask_app.py`, `redis_eventconsumer.py`); they turn input into a command, call `bus.handle`, and turn the outcome into a response.
- Root modules: make `bootstrap.py` the composition root, `views.py` the read-only queries, and `config.py` a set of functions (`get_postgres_uri()`, `get_api_url()`) that read `os.environ` with local-dev defaults instead of import-time constants.
- Tests and tooling: split `tests/unit`, `tests/integration`, `tests/e2e` with shared fixtures in `tests/conftest.py`; ship a `Dockerfile`, a `docker-compose.yml` (env vars, `src` and `tests` mounted as volumes, `PYTHONDONTWRITEBYTECODE=1`) and a `Makefile`.
- SQLAlchemy 2.x: replace the book's 1.x forms: classical `mapper()` with `map_imperatively` on one shared `registry()`, raw SQL strings in `session.execute` with `text()`, and `dict(row)` with `dict(row._mapping)`.

## Domain model

- Value object: model data without identity as `@dataclass(frozen=True)` (or a `NamedTuple`) so equality and hashing come from all fields, for example `OrderLine(orderid: str, sku: str, qty: int)`.
- Mapped value object: when SQLAlchemy maps `OrderLine`, declare it `@dataclass(unsafe_hash=True)` instead of `frozen=True`.
- Entity: give objects with lasting identity an `__eq__` that compares the identifier (`Batch.reference`, False for other types) and a `__hash__` of that identifier, or no hash if they never go in sets or dict keys; treat the identifier as read-only.
- Entity state: keep internals underscored (`_purchased_quantity`, `_allocations: Set[OrderLine]`), expose derived values as properties (`allocated_quantity`, `available_quantity`), and write rules as methods (`can_allocate`, `allocate`, `deallocate`).
- Domain service: write logic that belongs to no entity or value object as a plain function in `model.py`, such as `allocate(line, batches) -> str` returning the chosen `batch.reference`.
- Magic methods: express domain ordering with dunders, such as `Batch.__gt__` on `eta` where `None` (warehouse stock) sorts before any date, so `sorted(batches)` yields the preferred batch first.
- Domain exception: name exceptions in the business language and raise them from the model (`class OutOfStock(Exception)`).

## Aggregates

- Root: pick one entity to own a cluster of objects (`Product`, keyed by `sku`, holding every `Batch` for that SKU), change anything inside only through its methods, and move domain services onto it (`allocate(line, batches)` becomes `Product.allocate(line)`).
- Consistency boundary: place each invariant that spans objects (never over-allocate a SKU) inside one aggregate, keep it as small as the invariant allows, and hold only the data this bounded context needs.
- One aggregate per transaction: load and change a single aggregate per command; reach other aggregates, notifications and read models through event handlers, each in its own unit of work, and accept eventual consistency between them.
- One repository per aggregate: expose only repositories that return aggregates (`uow.products`); extra lookups such as `get_by_batchref` also return one aggregate.
- Version number: add `version_number: int = 0` to the root and increment it in every method that changes the aggregate (`allocate`), so every write touches the `products` row (`sku` primary key, `version_number` not null, default 0).
- Optimistic concurrency: create the engine with `isolation_level="REPEATABLE READ"` (in `DEFAULT_SESSION_FACTORY`, see Unit of work); when two transactions update the same product, the later commit fails with "could not serialize access due to concurrent update", so retry the whole operation. For pessimistic locking, use `.with_for_update()` in the repository `get` instead.
- Concurrency test: against real Postgres, start two threads that allocate the same SKU and sleep before committing, then assert the version rose by one and exactly one exception was raised.

```python
class Product:
    def __init__(self, sku: str, batches: List[Batch], version_number: int = 0):
        self.sku, self.batches = sku, batches
        self.version_number = version_number
        self.events = []  # type: List[events.Event]
    def allocate(self, line: OrderLine) -> str:
        try:
            batch = next(b for b in sorted(self.batches) if b.can_allocate(line))
            batch.allocate(line)
            self.version_number += 1
            self.events.append(events.Allocated(line.orderid, line.sku, line.qty, batch.reference))
            return batch.reference
        except StopIteration:
            self.events.append(events.OutOfStock(line.sku))
            return None
```

## Repository

- Port: define `AbstractRepository(abc.ABC)` in `adapters/repository.py` with only `add(product)` and `get(sku)` while the ORM session tracks changes for the unit of work to commit; add `update` only for an ORM that does not track them (see Django), and model deletion as a soft-delete method on the aggregate (`batch.cancel()`).
- Seen tracking: route public methods through abstract `_add` and `_get` so every aggregate passed in or loaded lands in `self.seen` (sketch below); subclasses call `super().__init__()`.
- Extra queries: copy the public/private pair (`get_by_batchref` calling `_get_by_batchref`) and return one aggregate; send list-style reads to views.
- SQLAlchemy adapter: write `SqlAlchemyRepository(session)` with `_add` as `self.session.add(product)`, `_get` as `self.session.query(model.Product).filter_by(sku=sku).first()`, and `_get_by_batchref` joining `model.Batch` and filtering `orm.batches.c.reference == batchref`; leave commits to the unit of work.
- ORM mapping: in `adapters/orm.py` declare `metadata` and `Table`s (`order_lines`, `products`, `batches`, `allocations`), then in `start_mappers()` map `OrderLine` to `order_lines`, `Batch` to `batches` with `_allocations = relationship(lines_mapper, secondary=allocations, collection_class=set)`, and `Product` to `products` with `batches = relationship(batches_mapper)`.
- Load hook: loading from the database skips `__init__`; register `@event.listens_for(model.Product, "load")` to set `product.events = []`.
- Fake: write `FakeRepository(products)` on the same base, calling `super().__init__()`, storing `self._products = set(products)`, with `_get` as `next((p for p in self._products if p.sku == sku), None)`.

```python
class AbstractRepository(abc.ABC):
    def __init__(self):
        self.seen = set()  # type: Set[model.Product]
    def add(self, product: model.Product):
        self._add(product)
        self.seen.add(product)
    def get(self, sku) -> model.Product:
        product = self._get(sku)
        if product:
            self.seen.add(product)
        return product
    # @abc.abstractmethod: _add(self, product), _get(self, sku)
```

## Unit of work

- Port: define `AbstractUnitOfWork(abc.ABC)` in `service_layer/unit_of_work.py` as a context manager exposing one repository per aggregate (`products: repository.AbstractRepository`) and abstract `_commit` and `rollback`.
- Rollback by default: make `__exit__` always call `self.rollback()`, so normal exit, early return or exception discards uncommitted work; a rollback after a commit changes nothing.
- New events: implement `collect_new_events()` to pop `events` off every aggregate in `self.products.seen` and yield them.
- SQLAlchemy adapter: write `SqlAlchemyUnitOfWork(session_factory=DEFAULT_SESSION_FACTORY)` where `DEFAULT_SESSION_FACTORY = sessionmaker(bind=create_engine(config.get_postgres_uri(), isolation_level="REPEATABLE READ"))`; `__enter__` sets `self.session = self.session_factory()` and `self.products = repository.SqlAlchemyRepository(self.session)` and returns `super().__enter__()`; `__exit__` calls `super().__exit__(*args)` then `self.session.close()`; `_commit` and `rollback` call the session.
- Fake: write `FakeUnitOfWork` with `self.products = FakeRepository([])` and `self.committed = False`, a `_commit` that sets `committed = True`, and a no-op `rollback`.

```python
class AbstractUnitOfWork(abc.ABC):
    products: repository.AbstractRepository
    def __enter__(self) -> AbstractUnitOfWork:
        return self
    def __exit__(self, *args):
        self.rollback()
    def commit(self):
        self._commit()
    def collect_new_events(self):
        for product in self.products.seen:
            while product.events:
                yield product.events.pop(0)
```

## Service layer and handlers

- Signature: write one function per use case in `service_layer/handlers.py`; take the command or event first, then dependencies named exactly as bootstrap provides them (`uow`, `notifications`, `publish`).
- Body: open `with uow:`, load the aggregate from `uow.products`, check preconditions against current state (raise `InvalidSku` when no product exists for the SKU), call one aggregate method, then end the block with `uow.commit()`; leave business rules to the aggregate.
- Inputs: take the message dataclass, or primitives (`orderid, sku, qty`) before a bus exists, so callers stay decoupled from the model.
- Outputs: return nothing from write handlers; callers read results through views.
- Side-effect handlers: ask only for the adapter you use, for example `send_out_of_stock_notification(event, notifications)` calling `notifications.send("stock@made.com", ...)` and `publish_allocated_event(event, publish)` calling `publish("line_allocated", event)`.
- Follow-up commands: let an event handler run another handler directly, as `reallocate(event: events.Deallocated, uow)` calls `allocate(commands.Allocate(**asdict(event)), uow=uow)`.

```python
def allocate(
    cmd: commands.Allocate,
    uow: unit_of_work.AbstractUnitOfWork,
):
    line = OrderLine(cmd.orderid, cmd.sku, cmd.qty)
    with uow:
        product = uow.products.get(sku=line.sku)
        if product is None:
            raise InvalidSku(f"Invalid sku {line.sku}")
        product.allocate(line)
        uow.commit()
```

## Commands and events

- Definition: write both as behavior-free `@dataclass` messages, commands subclassing `Command` in `domain/commands.py` and events subclassing `Event` in `domain/events.py`; type them together as `Message = Union[commands.Command, events.Event]`.
- Commands: name them imperatively (`Allocate(orderid, sku, qty)`, `CreateBatch(ref, sku, qty, eta: Optional[date] = None)`, `ChangeBatchQuantity(ref, qty)`) and map each to exactly one handler in `COMMAND_HANDLERS: Dict[Type[commands.Command], Callable]`.
- Events: name them in the past tense (`Allocated(orderid, sku, qty, batchref)`, `Deallocated(orderid, sku, qty)`, `OutOfStock(sku)`) and map each to a list of any number of handlers in `EVENT_HANDLERS: Dict[Type[events.Event], List[Callable]]`.
- Retries and replay: log each message before handling it (dataclass reprs can be pasted back to reproduce a failure), and optionally wrap event handlers in tenacity `Retrying(stop=stop_after_attempt(3), wait=wait_exponential())`, logging `RetryError`.

## Message bus

- Class: build `MessageBus(uow, event_handlers, command_handlers)` in `service_layer/messagebus.py`; it receives handlers with dependencies already bound and calls each with the message only.
- Loop: write `handle` as in the sketch (a queue drained from the front, dispatching by message type) and return nothing from it.
- Events: in `handle_event`, for each handler in `self.event_handlers[type(event)]`, inside `try` call `handler(event)` then `self.queue.extend(self.uow.collect_new_events())`; on `Exception` call `logger.exception` and `continue`, so one failing handler leaves the others and the command in place.
- Commands: in `handle_command`, look up `self.command_handlers[type(command)]`, call it, extend the queue the same way; on `Exception` call `logger.exception` and `raise` to the caller.
- Order: follow-up messages run inside the same `handle` call, first in first out.
- Scope: keep the bus as routing plus cross-cutting concerns (logging, retries, validation); `self.queue` lives on the instance and is not thread-safe.

```python
def handle(self, message: Message):
    self.queue = [message]
    while self.queue:
        message = self.queue.pop(0)
        if isinstance(message, events.Event):
            self.handle_event(message)
        elif isinstance(message, commands.Command):
            self.handle_command(message)
        else:
            raise Exception(f"{message} was not an Event or Command")
```

## Domain events

- Raise: append event instances to the aggregate's `self.events` where the fact happens, in domain terms (see the `Product` sketch).
- Outcomes as events: when a business outcome needs reactions rather than an error to the caller, record an event instead of raising; `Product.allocate` appends `OutOfStock` and returns `None`.
- Chains: let one method emit several events, as `Product.change_batch_quantity` sets `_purchased_quantity`, then calls `batch.deallocate_one()` while `available_quantity < 0`, recording `Deallocated` for each line; plan for a later transaction in the chain failing.
- Event tests: assert on recorded events in model tests (`product.events[-1] == events.OutOfStock(sku="SMALL-FORK")`).

## External integration

- Broker: integrate services through asynchronous messages on a broker (Redis pub/sub, Event Store, Kafka or RabbitMQ) instead of synchronous calls between services, and treat each service as its own consistency boundary.
- Inbound: write `entrypoints/redis_eventconsumer.py` with a module-level `r = redis.Redis(**config.get_redis_host_and_port())` and a `main()` that builds `bus = bootstrap.bootstrap()`, subscribes `r.pubsub(ignore_subscribe_messages=True)` to `"change_batch_quantity"`, and passes each message to `handle_change_batch_quantity(m, bus)`, which runs `json.loads(m["data"])`, builds `commands.ChangeBatchQuantity(ref=data["batchref"], qty=data["qty"])` and calls `bus.handle(cmd)`.
- Outbound: write `adapters/redis_eventpublisher.py` with `publish(channel, event: events.Event)` sending `json.dumps(asdict(event))`, and register `publish_allocated_event` for `events.Allocated` to publish on `"line_allocated"`.
- Translation: turn every inbound message into an internal command at the entrypoint, publish only the internal events other systems need, and map event classes to channels if one channel is not enough.
- Delivery: decide ordering, idempotency and at-least-once versus at-most-once delivery up front, and validate outbound events.
- E2E test: create data through the API, send with `redis_client.publish_message("change_batch_quantity", {...})`, listen with `redis_client.subscribe_to("line_allocated")`, and poll with tenacity `Retrying(stop=stop_after_delay(3), reraise=True)`.

## CQRS read side

- Split: send writes through commands, the bus and the domain; serve reads from `views.py` functions that bypass the domain model, repositories and handlers.
- API: return `"OK"` with 201 or 202 and no domain data from POST endpoints, and add a GET endpoint for state (`/allocations/<orderid>` returns `jsonify(result), 200`, or `"not found", 404` when empty).
- View: write `views.allocations(orderid, uow)` to open `with uow:`, run `uow.session.execute("SELECT sku, batchref FROM allocations_view WHERE orderid = :orderid", dict(orderid=orderid))` and return `[dict(r) for r in results]`; entrypoints pass `bus.uow`.
- Read model: declare a denormalized `allocations_view` table (`orderid`, `sku`, `batchref` as plain strings, no foreign keys) in the `orm.py` metadata and map no class to it.
- Updates: register `add_allocation_to_read_model` on `Allocated` (INSERT) and `remove_allocation_from_read_model` on `Deallocated` (DELETE by `orderid` and `sku`), each opening `with uow:`, executing SQL on `uow.session` and committing, so the read model updates in its own transaction.
- Staleness and rebuild: accept a slightly stale read side, and rebuild it by querying current allocations on the write side and calling `add_allocation_to_read_model` for each.
- Options: read through repositories or ORM queries when reads use the write model's concepts, and through hand-written SQL, denormalized tables or a separate store such as Redis (`hset` and `hgetall`) when they diverge; swapping stores touches only the two handlers and the view.

## Dependency injection and bootstrap

- Composition root: write `bootstrap()` in `src/allocation/bootstrap.py` to set production defaults, run once-only startup work (`orm.start_mappers()`, logging), bind dependencies into every handler, and return the `MessageBus`.
- Defaults: default `uow` to `unit_of_work.SqlAlchemyUnitOfWork()` and `publish` to `redis_eventpublisher.publish`; for a dependency whose constructor has side effects (`EmailNotifications()` opens an SMTP connection), default the parameter to `None` and build it inside `bootstrap`.
- Binding: collect `{"uow": uow, "notifications": notifications, "publish": publish}` and wrap every entry of `handlers.EVENT_HANDLERS` and `handlers.COMMAND_HANDLERS` with `inject_dependencies`, which matches handler parameter names (sketch below).
- Alternatives: hand-written lambdas per handler, `functools.partial(allocate, uow=uow)`, or handler classes with dependencies in `__init__` and the message in `__call__` all work; reach for a DI framework (Inject, Punq) only when you need injection in many places or have chains of dependencies.
- Adapter recipe: define an ABC (`AbstractNotifications.send(destination, message)`), implement it (`EmailNotifications(smtp_host, port)` over `smtplib.SMTP`), fake it (`FakeNotifications` appending to `self.sent = defaultdict(list)`), and integration-test the real one against a local stand-in such as MailHog; keep simple dependencies as plain callables (`publish`).
- Callers: in entrypoints call `bus = bootstrap.bootstrap()` once (module level in `flask_app.py`, inside `main()` of the consumer) and use only `bus.handle(cmd)` and `bus.uow`; in tests pass fakes as keyword arguments (see Testing strategy).

```python
def bootstrap(
    start_orm: bool = True,
    uow: unit_of_work.AbstractUnitOfWork = unit_of_work.SqlAlchemyUnitOfWork(),
    notifications: AbstractNotifications = None,
    publish: Callable = redis_eventpublisher.publish,
) -> messagebus.MessageBus:
    ...  # default notifications, start mappers, build the two injected handler dicts
    return messagebus.MessageBus(uow=uow, event_handlers=injected_event_handlers,
                                 command_handlers=injected_command_handlers)

def inject_dependencies(handler, dependencies):
    params = inspect.signature(handler).parameters
    deps = {name: dependency for name, dependency in dependencies.items() if name in params}
    return lambda message: handler(message, **deps)
```

## Testing strategy

- Shape: write one end-to-end happy-path test per feature plus one end-to-end test for all unhappy paths, most tests against the service layer with fakes, and a small core of domain-model tests; drop to model tests (low gear) when starting a project or untangling hard domain logic, and delete them once service-layer tests cover the behavior.
- Service-layer tests: build the bus with `bootstrap_test_app()`, which returns `bootstrap.bootstrap(start_orm=False, uow=FakeUnitOfWork(), notifications=FakeNotifications(), publish=lambda *args: None)`; set up state only by handling commands, then assert on fake state (`bus.uow.products.get(sku)`, `bus.uow.committed`, or `fake_notifs.sent["stock@made.com"]` after passing your own `fake_notifs` to `bootstrap`) or on `pytest.raises(handlers.InvalidSku)`.
- Missing services: if a service-layer test has to build domain objects, add the missing command and handler instead.
- Fakes over mocks: fake your own abstractions (repository, unit of work, notifications) instead of `mock.patch` or the SQLAlchemy session, and assert on end state.
- Integration tests: exercise real adapters, such as the repository and the unit of work (rollback by default and on error) against in-memory SQLite (`metadata.create_all` on the engine, `start_mappers()` in a fixture with `clear_mappers()` on teardown), views through a `sqlite_bus` fixture built by `bootstrap.bootstrap(start_orm=True, uow=unit_of_work.SqlAlchemyUnitOfWork(sqlite_session_factory), ...)`, concurrency against Postgres, and email against MailHog.
- E2E tests: run them against the containers, set up data through the API (`post_to_add_batch`) rather than SQL, keep tests apart with `random_sku`, `random_batchref` and `random_orderid`, and poll for asynchronous results.
- Event chains: test multi-handler flows edge to edge through the real bus; isolate a handler with a fake bus only when chains get complicated.

## Django

- Separation: keep the domain model as plain classes in `allocation/domain` and put Django models in a separate package (`src/djangoproject/alloc/models.py`) that imports the domain model; Django has no classical mapper, so translate explicitly between the two.
- Translation methods: give each Django model `to_domain()` (build `domain_model.Batch(ref=..., sku=..., qty=..., eta=...)` and fill `_allocations` from `allocation_set`) and a `@staticmethod update_from_domain(batch)` that upserts by `reference` (try `objects.get`, except `DoesNotExist`), copies fields (`qty = batch._purchased_quantity`), saves, and resets `allocation_set` from `Allocation.from_domain(line, b)`; value objects may use `get_or_create`.
- Repository: write `DjangoRepository(AbstractRepository)` whose `add` calls `super().add(batch)` (recording it in `seen`) then `update(batch)`, whose `update` calls `django_models.Batch.update_from_domain(batch)`, whose `_get` returns `django_models.Batch.objects.filter(reference=reference).first().to_domain()`, and whose `list` maps `to_domain()` over all rows.
- Unit of work: write `DjangoUnitOfWork` whose `__enter__` sets `self.batches = repository.DjangoRepository()` and calls `transaction.set_autocommit(False)`, whose `__exit__` calls `super().__exit__(*args)` then `set_autocommit(True)`, whose `commit` calls `self.batches.update(batch)` for every batch in `self.batches.seen` before `transaction.commit()` (Django does not track domain objects), and whose `rollback` calls `transaction.rollback()`.
- Views: write `@csrf_exempt` view functions that `json.loads(request.body)`, call the unchanged service layer with `unit_of_work.DjangoUnitOfWork()`, and return `JsonResponse` or `HttpResponse` with status codes; set `DJANGO_SETTINGS_MODULE` and call `django.setup()` first.
- Tests: use pytest-django, marking repository tests `@pytest.mark.django_db` and unit-of-work tests `@pytest.mark.django_db(transaction=True)`.
- Existing Django apps: start with a `logic.py` per app, add a service layer when views duplicate orchestration, gather reads in one place, organize modules by business concern rather than Django app, and add Repository and Unit of Work only if faster tests and decoupling justify the boilerplate.

## Validation

- Kinds: separate syntax (message shape: required fields, types, ranges), semantics (does the message make sense against current state, such as the product existing) and pragmatics (can the business honor it, such as enough stock).
- Syntax at the edge: validate message shape before any handler runs, so handlers and the model receive only well-formed messages; put it on the message class (`schema.Schema({...}, ignore_extra_keys=True)` plus a `from_json` classmethod) or in a `command(name, **fields)` factory built on `make_dataclass`; a bus method `handle_message(name, body)` can parse with `from_json` and log and re-raise `ValidationError`, which the API maps to 400 and the consumer logs and skips.
- Tolerant reader: read only the fields you use, ignore extra keys, treat identifiers such as SKUs and order IDs as opaque strings, keep message-validation code inside each service, and be strict about what you emit.
- Semantics in handlers: put preconditions in an `ensure` module (`ensure.product_exists(event, uow)` raising `ProductNotFound`, a `MessageUnprocessable` subclass carrying the message and `sku`), call them inside the handler's `with uow:` on the same uow, and map them to responses (`ProductNotFound` to 404).
- Idempotency: raise `SkipMessage(reason)` for duplicate or outdated messages (a batch that already exists) and have the bus log a warning and skip them.
- Pragmatics in the domain: keep business-rule refusals (out of stock) in the aggregate, and put any rule the domain model can test there rather than in a precondition.
