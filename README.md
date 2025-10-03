# bagbot
Bot for accumulating alpha in the Bittensor Alpha Group

Be very careful before using this bot.  There are no guarantees nor instructions at this time as its being updated frequently.

Setup:

1. Clone the repository:

```
git clone https://github.com/taotemplar/bagbot.git
```


2. Enter the bagbot directory:

```
cd bagbot
```

3. Install, create, and activate your python virtualenv:

```
pip3 install virtualenv
virtualenv ~/.bagbotvirtualenv/
source ~/.bagbotvirtualenv/bin/activate

```

4. Install the requirements:

```
pip3 install -r requirements.txt
```

5. Create a file containing your wallet's password (with no whitespace around it or any other characters)
6. Setup your buy/sell settings by copying the top part of the `bagbot_settings.py` file to a new file: `bagbot_settings_overrides.py` . Do not copy the bottom 4 lines.
7. Change the `WALLET_PW_FILE` variable to point at that file's location.
8. 
9. Make a file called 
10. Edit the file as desired, there are notes about what the variables do in the file


To start the bot, activate your virtualenv and run by doing:

```
source ~/.bagbotvirtualenv/bin/activate
python3 bagbot.py
```
