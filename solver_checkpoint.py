import pickle
import sqlite3


class TrackedDict(dict):
    def __init__(self):
        super().__init__()
        self.dirty = set()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.dirty.add(key)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.dirty.add(key)

    def pop(self, key, *default):
        if key in self:
            value = self[key]
            del self[key]
            return value
        if default:
            return default[0]
        raise KeyError(key)

    def clear(self):
        self.dirty.update(self)
        super().clear()

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value


class Checkpoint:
    names = ('memo', 'best_guesses', 'lower_bounds', 'pending')

    def __init__(self, output, fingerprint, solver):
        self.path = output / 'solver_checkpoint.sqlite3'
        self.fingerprint = fingerprint
        self.solver = solver
        self.connection = sqlite3.connect(self.path)
        self.connection.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS states '
                                '(cache TEXT, key BLOB, value BLOB, PRIMARY KEY(cache,key)) WITHOUT ROWID')
        metadata = dict(self.connection.execute('SELECT name,value FROM metadata'))
        self.caches = {name: TrackedDict() for name in self.names}
        try:
            if metadata:
                if metadata.get('fingerprint') != fingerprint or metadata.get('format') != 'integer-v2':
                    raise ValueError('Checkpoint inputs or format changed. Use a different --output directory.')
                for name, key, value in self.connection.execute('SELECT cache,key,value FROM states'):
                    dict.__setitem__(self.caches[name], pickle.loads(key), pickle.loads(value))
                print(f'Restored incremental checkpoint: {len(self.caches["memo"])} exact states, '
                      f'{len(self.caches["pending"])} unfinished states.', flush=True)
            else:
                legacy = output / 'solver_checkpoint.pkl'
                if legacy.exists():
                    print('Migrating legacy checkpoint to integer IDs (original file retained)...', flush=True)
                    with legacy.open('rb') as file:
                        state = pickle.load(file)
                    if state['fingerprint'] != fingerprint:
                        raise ValueError('Legacy checkpoint inputs changed. Use a different --output directory.')
                    self._migrate(state)
                self.save()
            for name, cache in self.caches.items():
                setattr(solver, name, cache)
        except BaseException:
            self.connection.close()
            raise

    def _migrate(self, state):
        solver = self.solver

        def ids(words):
            return tuple(sorted(solver.answer_index[w] if isinstance(w, str) else int(w) for w in words))

        def key(old):
            return (*old[:-1], ids(old[-1]))

        def guess(old):
            return solver.guess_index[old] if isinstance(old, str) else old

        order = tuple(solver.guess_index[w] for w in solver.GUESS_ORDER)
        for name in self.names:
            legacy_cache = state.pop(name, {})


            while legacy_cache:
                old_key, old_value = legacy_cache.popitem()
                new_key = key(old_key)
                t = new_key[1] if new_key[0] == 'capped' else new_key[0]
                if len(new_key[-1]) <= 4 - t:
                    continue
                value = old_value
                if name == 'best_guesses':
                    value = guess(value)
                elif name == 'pending':
                    completed, best, winner = value[:3]
                    value = (completed, best, guess(winner), value[3] if len(value) > 3 else order)
                self.caches[name][new_key] = value
        print(f'Migrated {len(self.caches["memo"])} exact states and '
              f'{len(self.caches["pending"])} unfinished states.', flush=True)

    def save(self):
        changed = sum(len(cache.dirty) for cache in self.caches.values())
        with self.connection:
            self.connection.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)',
                                        [('format', 'integer-v2'), ('fingerprint', self.fingerprint)])
            for name, cache in self.caches.items():
                for key in cache.dirty:
                    encoded = pickle.dumps(key, protocol=pickle.HIGHEST_PROTOCOL)
                    if key in cache:
                        self.connection.execute('INSERT OR REPLACE INTO states VALUES (?,?,?)',
                                                (name, encoded, pickle.dumps(cache[key], protocol=pickle.HIGHEST_PROTOCOL)))
                    else:
                        self.connection.execute('DELETE FROM states WHERE cache=? AND key=?', (name, encoded))
        for cache in self.caches.values():
            cache.dirty.clear()
        return changed

    def close(self):
        self.connection.close()
