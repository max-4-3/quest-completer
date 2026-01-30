# Quest Completer

This is a quest completer for discord written in python.

---

## Dependencies

- `aiohttp`
- `rich`
- `pydotmap`

---

## Documentation

Most (nearly all) of resources are taken from:
[Discord Userdoccers](https://docs.discord.food/resources/quests)

---

## Setup

Create a `.env` at project root (or where `main.py` is located) file with following format:

```ini
TOKEN="YOUR_TOKEN"
```

or run the script with `TOKEN="YOUR_TOKEN"` at the begining

---

## Usage

### Using **uv** (recommended)

Run directly with:

```bash
uv run main.py
```

---

### Default (without uv)

#### Create a virtual environment

```bash
python -m venv .venv
```

#### Activate the virtual environment

- **Windows**
  - **cmd**

    ```bat
    .venv\Scripts\activate
    ```

  - **PowerShell**

    ```ps
    .venv\Scripts\Activate.ps1
    ```

- **Linux / macOS**

  ```bash
  source .venv/bin/activate
  ```

#### Install **[Dependencies](#dependencies)**

```bash
pip install aiohttp rich pydotmap
```

#### Run

```bash
python main.py
```
