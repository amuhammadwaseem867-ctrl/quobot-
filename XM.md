# XM + MT5 forex mode ($50 account)

Quobot ab forex ke liye bhi signal deta hai: **BUY/SELL, stop-loss, take-profit aur lot size**, aapke balance ke hisaab se.
Bot khud trade **nahi** karta. Aap MT5 mein khud order lagate hain.

## Pehle sach baat (zaroor parhein)

- **$50 bohot chhota account hai.** Leverage (1:500, 1:1000) ki wajah se ek ghalat trade poora account khatam kar sakta hai.
  Isi liye bot har trade par sirf **1%** risk karta hai = **$0.50**. Paisa dheere badhega, lekin account bacha rahega.
- **Micro account lein, Standard nahi.** Standard par sab se chhota lot (0.01) bhi aksar $1-3 risk karta hai, yaani 2-6%.
  Micro par lot 100 guna chhota hota hai, is liye stop-loss sahi jagah lag sakta hai.
- Koi bot har trade nahi jeetta. Bot har signal ke saath batata hai ke purane milte julte signals kitni baar target tak pohanche.
  1:2 reward par break-even **33%** hai. Agar history is se kam ho to bot khud "Skip it" likh deta hai.
- Pakistan mein bahar ke broker par paisa bhejne ke rules (SBP/SECP) apne zimme check karein.
- Pehle **demo account** par 2 hafte chala kar dekhein, phir real $50.

## 1. XM account kholein

1. Website **xm.com** par jaein (sirf asli site, koi link WhatsApp/Telegram se na kholein).
2. **Open an account** dabayein. Country: Pakistan. Email aur password dein.
3. Settings chunein:
   - Trading platform: **MT5**
   - Account type: **Micro**
   - Base currency: **USD**
   - Leverage: **1:100 ya 1:200** (kam leverage = ghalti par kam nuqsan; bot ka lot size waisa hi rehta hai)
4. Email confirm karein. XM aapko **MT5 login number** aur **server name** email karega (jaise `XMGlobal-MT5 3`). Ye sambhal kar rakhein, kisi ko na dein.
5. **Verification:** Members Area mein CNIC (dono taraf) aur address proof (bijli/gas bill ya bank statement) upload karein.
6. **Deposit $50:** Members Area > Deposit. Jo tareeqa aapke liye available ho (card, bank, e-wallet) wo chunein. Fees zaroor check karein.

## 2. MT5 connect karein

1. Phone par **MetaTrader 5** install karein (MetaQuotes ki official app) ya PC par XM ki website se MT5.
2. App kholein > **Manage accounts** > **+** > search mein **XM Global** likhein.
3. Email wala **server**, **login number** aur **password** dalein.
4. **Quotes** (Market Watch) mein **+** dabayein aur ye symbols add karein: `EURUSDmicro`, `GBPUSDmicro`, `USDJPYmicro`, `GOLDmicro`.
   Agar naam thoda mukhtalif ho (jaise koi aur suffix), wahi naam use karein jo aapke MT5 mein dikhta hai.
5. Gold ka contract size check karein: symbol par long press > **Specification** > Contract size. Standard par 100 oz hota hai.
   Agar micro par mukhtalif ho to mujhe bata dein, main bot mein theek kar dunga.

## 3. Bot ko apna balance batayein

`.env` file mein ye lines add karein (ya change karein):

```
FX_BALANCE=50
FX_RISK=1
FX_ACCOUNT=micro
FX_LEVERAGE=200
```

Balance badle to `FX_BALANCE` update kar dein.

## 4. Signal lena

- Telegram par **/fx** bhejein: majors + gold mein se abhi ke sab se safe trades.
- **/fx EURUSD** bhejein: ek pair ka poora plan aur reasons.
- `start-bot.bat` ab har 15 minute khud bhi forex check karta hai aur **sirf tab** message karta hai jab koi valid trade ho.
- PC par: `python -m today_trader fx` ya `python -m today_trader fx EURUSD --balance 50`

Forex signals 15-minute candles par hain (1 minute par spread hi saara faida kha jata hai).

## 5. MT5 mein order lagana

Signal kuch aisa aayega:

```
🟢 BUY EURUSDmicro
💵 Entry: 1.08452
🛑 Stop-loss: 1.08302  (15 pips)
🎯 Take-profit: 1.08752  (30 pips)
📦 Lot size: 0.33 on a Micro account
⚖️ If stop hits: -$0.50 (1.0% of $50) · if target hits: +$1.00
```

1. MT5 mein symbol (`EURUSDmicro`) par tap > **Trade** (New order).
2. Type: **Market Execution**. Volume: bot wala **lot size** (0.33).
3. **Stop Loss** aur **Take Profit** mein bot wale prices dalein. **Stop-loss kabhi khaali na chhorein.**
4. Signal BUY ho to **Buy by Market**, SELL ho to **Sell by Market**.
5. Agar price pehle hi target ki taraf aadha raasta chal chuki ho to trade chhor dein.

## Rules jo account bachate hain

- Ek waqt mein **zyada se zyada 2 trades**.
- Din mein **3 loss** ho jaein to us din band.
- Stop-loss ko kabhi door na karein. Loss ke baad lot double na karein.
- Bari news (NFP, CPI, interest rate) ke waqt trade na karein: spread achanak bohot barh jata hai.
