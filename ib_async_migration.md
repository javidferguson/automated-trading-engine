# Migration Guide: ib_insync to ib_async

## Overview

This project uses **ib_async** instead of **ib_insync**. `ib_async` is the actively maintained successor to `ib_insync`, providing better performance, bug fixes, and new features while maintaining API compatibility.

## Why ib_async?

- **Active Maintenance**: ib_insync is no longer actively maintained; ib_async is the community-supported continuation
- **Bug Fixes**: Includes numerous fixes for issues in ib_insync
- **Enhanced Features**: 
  - Custom defaults for empty prices/sizes
  - Better timezone handling
  - Improved greeks object operations
  - Better spread/bag contract support
- **Performance**: Optimized for modern Python versions
- **Compatibility**: Drop-in replacement with minimal code changes

## Key Differences

### 1. Import Statement

**Old (ib_insync):**
```python
from ib_insync import IB, Stock, Option, MarketOrder
```

**New (ib_async):**
```python
from ib_async import IB, Stock, Option, MarketOrder
```

### 2. Installation

**Old:**
```bash
pip install ib_insync==0.9.86
```

**New:**
```bash
pip install ib_async==2.1.0
```

### 3. Enhanced Features in ib_async

#### Custom Empty Value Defaults

ib_async allows you to customize how empty/unset values are handled:

```python
from ib_async import IB, IBDefaults
import pytz

# Custom defaults (ib_async only)
eastern = pytz.timezone("US/Eastern")
ib = IB(defaults=IBDefaults(
    emptyPrice=None,      # Instead of -1
    emptySize=None,       # Instead of 0
    unset=None,          # Instead of NaN
    timezone=eastern     # Instead of UTC
))
```

#### Enhanced Greeks Operations

```python
# ib_async supports math operations on greeks objects directly
greeks1 = option1.modelGreeks
greeks2 = option2.modelGreeks

# Calculate spread greeks
spread_greeks = greeks1 + greeks2  # Works in ib_async!
```

## API Compatibility

The core API remains **100% compatible**. All methods used in this project work identically:

| Method | ib_insync | ib_async | Notes |
|--------|-----------|----------|-------|
| `connectAsync()` | ✅ | ✅ | Identical |
| `reqSecDefOptParams()` | ✅ | ✅ | Identical |
| `qualifyContracts()` | ✅ | ✅ | Identical |
| `reqMktData()` | ✅ | ✅ | Identical |
| `reqHistoricalData()` | ✅ | ✅ | Identical |
| `placeOrder()` | ✅ | ✅ | Identical |
| `ticker()` | ✅ | ✅ | Identical |

## No Code Changes Required

For this project, **zero code changes** were needed beyond the import statement. The migration was:

1. Changed `from ib_insync import ...` to `from ib_async import ...`
2. Updated `requirements.txt` from `ib_insync==0.9.86` to `ib_async==2.1.0`
3. Done!

All functionality works exactly the same.

## Version History

| Library | Last Version | Status |
|---------|--------------|--------|
| ib_insync | 0.9.86 (2022) | No longer maintained |
| ib_async | 2.1.0 (2024) | Actively maintained |

## Testing the Migration

To verify everything works after migration:

```bash
# 1. Uninstall old library
pip uninstall ib_insync

# 2. Install new library
pip install ib_async==2.1.0

# 3. Run tests
python main.py
```

## Troubleshooting

### Issue: Import Error
```
ModuleNotFoundError: No module named 'ib_async'
```

**Solution:**
```bash
pip install ib_async
```

### Issue: Both Libraries Installed
If you have both installed, remove ib_insync:
```bash
pip uninstall ib_insync
pip install ib_async
```

### Issue: Old Syntax in Code
Search your codebase for:
```bash
grep -r "from ib_insync" .
grep -r "import ib_insync" .
```

Replace all instances with `ib_async`.

## Resources

- **ib_async Documentation**: https://ib-api-reloaded.github.io/ib_async/
- **GitHub Repository**: https://github.com/ib-api-reloaded/ib_async
- **PyPI Package**: https://pypi.org/project/ib_async/
- **Release Notes**: https://github.com/ib-api-reloaded/ib_async/releases

## Community Support

- **GitHub Issues**: Report bugs and request features
- **Discussions**: Community Q&A and examples
- **Pull Requests**: Contributions welcome

## Summary

✅ **ib_async is a drop-in replacement for ib_insync**  
✅ **100% API compatible for our use case**  
✅ **Actively maintained with bug fixes and improvements**  
✅ **Recommended for all new projects**  

The migration is straightforward and provides better long-term support.
