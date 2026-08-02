# Sloppy code

> **Status: directly gathered this session.** The automated sloppy-code iteration did not run (session limit), so these were collected by hand via grep + inspection and are all confirmed present. See [README.md](README.md).

Dead/commented-out code, leftover debug scaffolding, broad exception handling, stale TODOs, and stray files. Gathered and confirmed directly in this session (the third iteration).

_9 findings — 0 high, 2 medium, 7 low._

---

## 1. Debug __main__ scratch block with bare print() statements shipped in a library module

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:1761-1779`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L1761)

**What.** The active-backend BitVector module ends with an `if __name__ == "__main__":` block full of exploratory `print(...)` calls (bitarray subclass checks, type prints). It is dead scratch code that ships inside the installed package; it never runs on import but signals an unfinished module and clutters the file.

**Evidence.**

```python
if __name__ == "__main__":
    print("-------------------------------")
    print(issubclass(BitVector, bitarray))
    ...
    print(a_bitarray); print(a_bitarray_2); print(bitArray2)
```

**Suggestion.** Delete the block (or move any still-useful snippet into a test).

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 2. Large blocks of commented-out dead code throughout the bitarray BitVector implementation

**Severity:** medium · **Confidence:** high · [`bytemaker/bitvector/bitvector_with_bitarray_speedup.py:420-437, 614-630, 940-942, 1006, 1121-1122, 1201-1213, 1495-1500`](../bytemaker/bitvector/bitvector_with_bitarray_speedup.py#L420)

**What.** Many multi-line stretches of commented-out code remain: an old from_bytes/frombytes pair (420-437), hex/oct/bin/to_base bodies (614-630), isinstance dispatch experiments (940-942, 1201-1213), a commented __reverse__ (1006), swap_endianness (1121-1122), and translate/maketrans stubs (1495-1500). Commented code rots and obscures what the module actually does.

**Evidence.**

e.g. lines 614-630:
```python
# def hex(self, sep: Optional[str] = None, bytes_per_sep: int = 1) -> str:
#     ...
# def oct(self) -> str:
#     return ba2base(8, self)
# def bin(self) -> str:
#     return ba2base(2, self)
```

**Suggestion.** Remove; git history preserves anything worth recovering.

_Note: this file (`bitvector_with_bitarray_speedup.py`) is the **active backend** in the current environment (bitarray installed), so this divergence affects the default runtime here._

---

## 3. Stray zero-byte ':TEMP_UNUSED' file at the repo root

**Severity:** low · **Confidence:** high · [`:TEMP_UNUSED (repo root, adjacent to the package):-`](../:TEMP_UNUSED (repo root, adjacent to the package)#L1)

**What.** A zero-byte file literally named ':TEMP_UNUSED' sits at the repo root. The leading colon is an invalid filename character on Windows and strongly suggests an accidental shell-redirect artifact. It is outside bytemaker/ but ships with the checkout.

**Evidence.**

`-rw-r--r-- 1 belmo 197609 0 Jul 31 01:48 :TEMP_UNUSED`

**Suggestion.** Delete it (and check the .gitignore / whatever command created it).

---

## 4. 13 TODO/FIXME/Todo markers, several stale or load-bearing

**Severity:** low · **Confidence:** high · [`bytemaker (package-wide):bittype.py:349, string.py:112, bitvector_native.py:260/284/523, bitvector_with_bitarray_speedup.py:250/274/502/1013/1497/1500, bitvector_speedup.py:347, fixed.py:8`](../bytemaker (package-wide)#L349)

**What.** 13 TODO/FIXME/Todo comments remain, including a load-bearing `# TODO remove` on a deprecated path (bittype.py:349), unimplemented `errors=` parameters marked `# TODO` in all three BitVector impls, `# TODO support non-multiple-of-two bases`, and `# Todo: Verify memoization procedure`. A couple are aspirational deletions that can't fire until tests migrate (see observations 06).

**Evidence.**

e.g. `bittypes/bittype.py:349:    # TODO remove` ; `bitvector/bitvector_with_bitarray_speedup.py:1013:        # Todo: Verify memoization procedure`

**Suggestion.** Triage: convert real work to issues, delete stale markers, and resolve the load-bearing 'TODO remove' by migrating its callers.

---

## 5. Commented-out __hash__ implementation left in BitType

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/bittype.py:338-346`](../bytemaker/bittypes/bittype.py#L338)

**What.** A dead `# def __hash__(self): ... return hash(frozenset([self.value]))` sits in the BitType body, next to a `# TODO remove` (line 349). It leaves the hashability contract ambiguous.

**Evidence.**

```python
# def __hash__(self):
#     ...
#     return hash(frozenset([self.value]))
```

**Suggestion.** Decide hashability explicitly and delete the commented stub.

---

## 6. Commented-out int_format classproperty left in Int

**Severity:** low · **Confidence:** high · [`bytemaker/bittypes/int.py:591-592`](../bytemaker/bittypes/int.py#L591)

**What.** A dead `# def int_format(cls) -> str: / #     return Config.signed_int_format` remains in the Int class body.

**Evidence.**

```python
# def int_format(cls) -> str:
#     return Config.signed_int_format
```

**Suggestion.** Remove.

---

## 7. Commented-out debug print in reverse_ctype_endianness

**Severity:** low · **Confidence:** high · [`bytemaker/conversions/ctypes_.py:65`](../bytemaker/conversions/ctypes_.py#L65)

**What.** A leftover `# print(field_name, field_value, type(field_value))` debugging line sits in the hot loop of reverse_ctype_endianness.

**Evidence.**

```python
# print(field_name, field_value, type(field_value))
```

**Suggestion.** Delete.

---

## 8. Commented-out except block in the frozen-oracle to_bits path

**Severity:** low · **Confidence:** medium · [`bytemaker/_legacy_aggregate.py:286`](../bytemaker/_legacy_aggregate.py#L286)

**What.** A `# except Exception as e:` line is commented out inside the reference-oracle serialization path, leaving a half-disabled error handler that reads as unfinished. (The file is the deliberate frozen oracle, so this is cleanup, not a behavior change.)

**Evidence.**

```python
#     except Exception as e:
```

**Suggestion.** Either restore a real handler or remove the dangling comment.

---

## 9. Broad `except Exception` catches in several spots

**Severity:** low · **Confidence:** medium · [`bytemaker/conversions/aggregate_types.py:141 (also utils.py:249, bittype.py:129/142/474)`](../bytemaker/conversions/aggregate_types.py#L141)

**What.** Several `except Exception` handlers remain. The BitType ones (129/142/474) re-raise as ValueError with context (defensible), but aggregate_types.py:141 and utils.py:249 swallow broadly. The observations pass flagged bare-Exception as a theme; these are the remaining instances.

**Evidence.**

```python
# aggregate_types.py:141
    except Exception:
        ...
```

**Suggestion.** Narrow to the specific exception types where these swallow rather than re-raise.

---
