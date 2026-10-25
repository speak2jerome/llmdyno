# Open bug reports for semverlite 0.4.1

## #12: Release candidates sort in the wrong order

> We sort our release tags with `sorted(map(parse, tags))` and `1.0.0-rc.10` comes out *before* `1.0.0-rc.2`.
> The same happens with `beta.11` vs `beta.2`. Our release dashboard now shows the wrong "latest RC".

## #15: Versions that differ only in build metadata are "different"

> `parse("1.0.0+build.1") == parse("1.0.0+build.2")` is `False`, and using versions as dict keys
> gives duplicate entries for the same release. The semver spec says build metadata must be ignored
> when determining precedence.

## #17: Caret ranges on 0.x versions allow breaking upgrades

> `satisfies("0.3.0", "^0.2.3")` returns `True`, so our tool happily upgrades to a breaking 0.3.0.
> npm treats `^0.2.3` as `>=0.2.3 <0.3.0` and `^0.0.3` as `>=0.0.3 <0.0.4`.
