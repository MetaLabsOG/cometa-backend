const deflex = require('@deflex/deflex-sdk-js');
const algosdk = require('algosdk')

const ALGOD_ADDRESS = 'https://mainnet-api.algonode.cloud'
const ALGOD_TOKEN = ''

// TODO: REMOVE !!!
// m n e m o n i c  BRO
const ALGO_MNEMONIC = ''
const DEFLEX_API_KEY = ''

const ALGO_ID = 0
const GOBTC_ID = 386192725
const GOETH_ID = 386195940
const USDC_ID = 31566704

const SWAP_SKIP_PROBABILITY = 0.33
const TARGET_TOKEN_IDS = [ALGO_ID, GOBTC_ID, GOETH_ID, USDC_ID]

const SOURCE_TOKEN_ID = 924268058
const SOURCE_TOKEN_DECIMALS = 6
const MIN_SELL_AMOUNT = 100
const MAX_SELL_AMOUNT = 2900

async function run() {
    if (Math.random() < SWAP_SKIP_PROBABILITY) {
        console.log(`\nSkipping swap`)
        return
    }

    // FRY

    const targetInd = Math.floor(Math.random() * TARGET_TOKEN_IDS.length)
    const targetTokenId = TARGET_TOKEN_IDS[targetInd]
    const sellAmount = Math.random() * (MAX_SELL_AMOUNT - MIN_SELL_AMOUNT + 1) + MIN_SELL_AMOUNT
    const sellAmountMicros = Math.floor(sellAmount * Math.pow(10, SOURCE_TOKEN_DECIMALS))
    console.log(`\nSelling ${sellAmount} of token id ${SOURCE_TOKEN_ID} for token id ${targetTokenId}`)

    const deflexClient = deflex.DeflexOrderRouterClient.fetchMainnetClient(ALGOD_ADDRESS, ALGOD_TOKEN, '', undefined, undefined, DEFLEX_API_KEY)

    console.log(`\nFetching quote`)
    const quote = await deflexClient.getFixedInputSwapQuote(SOURCE_TOKEN_ID, targetTokenId, sellAmountMicros)
        .catch((e) => {
            console.log(`\nError fetching quote: ${e}`)
        });
    console.log(`\nGot quote: ${quote.quote} of token_id=${quote.fromASAID} for ${quote.amountIn} of token_id=${quote.toASAID}`)

    const algod = new algosdk.Algodv2(ALGOD_TOKEN, ALGOD_ADDRESS, '')
    const params = await algod.getTransactionParams().do()

    const requiredAppOptIns = quote.requiredAppOptIns
    console.log(`\nOpting into required apps: ${requiredAppOptIns}`)
    const sender = algosdk.mnemonicToSecretKey(ALGO_MNEMONIC)
    const accountInfo = await algod.accountInformation(sender.addr).do()
    const optedInAppIds = 'apps-local-state' in accountInfo ? accountInfo['apps-local-state'].map((state) => parseInt(state.id)) : []
    for (let i = 0; i < requiredAppOptIns.length; i++) {
        const requiredAppId = requiredAppOptIns[i]
        if (!optedInAppIds.includes(requiredAppId)) {
            const appOptInTxn = algosdk.makeApplicationOptInTxn(sender.addr, params, requiredAppId)
            const signedTxn = appOptInTxn.signTxn(sender.sk)
            await algod
                .sendRawTransaction(signedTxn)
                .do();
        }
    }
    console.log(`\nOpted into required apps: ${requiredAppOptIns}`)

    const txnGroup = await deflexClient.getSwapQuoteTransactions(sender.addr, quote, 5)
    console.log(`\nGot swap txn group with ${txnGroup.txns.length} txns`)

    const signedTxns = txnGroup.txns.map((txn) => {
        if (txn.logicSigBlob !== false) {
            return txn.logicSigBlob
        } else {
            let bytes = new Uint8Array(Buffer.from(txn.data, 'base64'))
            const decoded = algosdk.decodeUnsignedTransaction(bytes)
            return algosdk.signTransaction(decoded, sender.sk).blob
        }
    })
    const {txId} = await algod
        .sendRawTransaction(signedTxns)
        .do();
    console.log(`\nSent txn group: ${txId}`)
}

run()
