# bagbot
Bot for accumulating alpha in the Bittensor Alpha Group

USE AT YOUR OWN RISK!  There are no guarantees!


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

5. Create a new wallet:

```
btcli w create --wallet.name bagbot
```

6. Send a small amount to the wallet address, to find the address run and look for the ss58_address (eg: 5Dso...xAi3):

```
btcli w list
```

7. Setup your buy/sell settings by copying the top part of the `bagbot_settings.py` file to a new file: `bagbot_settings_overrides.py` .   DO NOT copy the bottom 4 lines.

8. In `bagbot_settings_overrides.py`:
 
* Change the `WALLET_PW` variable to your wallet's password.
* Edit the file as desired, there are notes about what the variables do in the file


To start the bot, activate your virtualenv and run by doing:

```
source ~/.bagbotvirtualenv/bin/activate
python3 bagbot.py
```
