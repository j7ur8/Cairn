---
name: cypher-blockchain
description: Blockchain and smart contract exploitation methodology covering reentrancy, integer overflow/underflow, access control, flash loan attacks, oracle manipulation, MEV, delegatecall injection, and Solidity/Vyper audit patterns.
version: 0.1.0
finding_types: [REPO_FINDING, VULN_CANDIDATE, EXPLOIT_RESULT, SECRET_LEAK]
destructiveness: low
tags: [ctf, blockchain, solidity, smart-contract, evm]
---

# Cypher Blockchain / Smart Contract Skill

Use this skill for CTF blockchain/Web3 challenges, smart contract auditing, DeFi exploit reproduction, and EVM-based vulnerability research.

## Initial triage

1. Check the network: Ethereum mainnet/testnet, L2, private chain (Anvil/Ganache/Hardhat node)
2. Read the challenge description: contract address(es), ABI, source code (if provided), transaction hashes
3. Set up environment:
   ```bash
   # For local CTF challenges
   cast block-number --rpc-url <rpc-url>
   cast chain-id --rpc-url <rpc-url>
   # Check balance
   cast balance <address> --rpc-url <rpc-url>
   ```
4. Get contract bytecode and verify/analyze:
   ```bash
   cast code <contract-address> --rpc-url <rpc-url>
   cast storage <contract-address> --rpc-url <rpc-url>
   ```

## Tool stack

| Tool | Use |
|------|-----|
| **Foundry (forge/cast)** | Compile, test, deploy, interact with contracts |
| **Hardhat** | JavaScript/TypeScript development and testing framework |
| **echidna** | Fuzzing for smart contracts |
| **slither** | Static analysis |
| **mythril** | Symbolic execution |
| **4byte.directory** | Function signature → method name lookup |
| **Tenderly / Phalcon** | Transaction simulation and debugging |
| **Etherscan/DethCode** | Source verification |

## Common vulnerability patterns

### 1. Reentrancy

```solidity
// VULNERABLE
function withdraw(uint amount) external {
    require(balances[msg.sender] >= amount);
    (bool success, ) = msg.sender.call{value: amount}(""); // External call
    require(success);
    balances[msg.sender] -= amount; // State update AFTER external call
}

// Exploit contract:
// receive() external payable {
//     if (address(target).balance >= amount) {
//         target.withdraw(amount); // Re-enter before balance updated
//     }
// }
```

**Variants:**
- **Single-function**: Re-enter the same function
- **Cross-function**: Re-enter a different function that also modifies state
- **Cross-contract**: Re-enter a different contract that calls back
- **Read-only reentrancy**: View function returns stale data mid-exploit

**CTF reentrancy check:**
1. Find all external calls (`.call{}`, `.transfer`, `.send`, token transfers)
2. Check if state changes happen after external calls
3. Check for `nonReentrant` modifier
4. Build exploit contract that re-enters in `receive()` or `fallback()`

### 2. Integer overflow / underflow (Solidity <0.8.0)

```solidity
// Solidity ^0.8.0 has built-in overflow protection
// For older versions (^0.4, ^0.5, ^0.6, ^0.7):
uint8 max = 255;
max += 1; // Overflows to 0
uint8 min = 0;
min -= 1; // Underflows to 255
```

**CTF pattern:**
- Token balance overflow: buy tokens cheap, overflow during addition → massive balance
- Transfer overflow: `require(balances[from] - amount >= 0)` in unchecked block

### 3. Access control

```solidity
// VULNERABLE: no access control
function setOwner(address _newOwner) external {
    owner = _newOwner;
}

// VULNERABLE: tx.origin for auth
function transfer(address to, uint amount) external {
    require(tx.origin == owner); // Phished owner calls attacker's contract → bypasses
    // ...
}

// Check: onlyOwner, Ownable inheritance, missing modifiers
```

### 4. Delegatecall injection

```solidity
// VULNERABLE: user-controlled delegatecall target
function execute(address target, bytes calldata data) external {
    (bool success, ) = target.delegatecall(data); // Executes in CALLER's context!
}
// Attacker deploys a contract with function that modifies owner/slot0
```

**Storage collision:** delegatecall uses calling contract's storage layout. If the delegated contract's storage layout is attacker-controlled → overwrite critical slots (owner, implementation, admin).

### 5. Flash loan attacks

Flash loans allow borrowing without collateral within a single transaction:

```solidity
// Borrow → manipulate price oracle → exploit → repay all in one tx
function attack() external {
    // 1. Flash loan massive tokens from lending pool
    // 2. Dump tokens on DEX → price oracle reports extreme price
    // 3. Borrow against inflated collateral / liquidate positions
    // 4. Repay flash loan + fee
}
```

### 6. Oracle manipulation

- **Spot price from DEX**: Manipulate DEX pair with a large trade → spot price changes dramatically
- **TWAP (Time-Weighted Average Price)**: More resistant, but can be manipulated over time
- **Centralized oracle**: Single source of truth — if compromised, entire protocol fails
- Check: where does the contract get its price feeds?

### 7. ERC20 peculiarities

- **Weird ERC20 tokens**: USDT doesn't return bool on transfer, some tokens have fees
- **Fee-on-transfer tokens**: `transfer(amount)` actually transfers `amount - fee`
- **Return value mismatch**: Some tokens return `false` instead of reverting on failure
- **Multiple entry points**: `transfer` and `transferFrom` with differing checks

### 8. Signature vulnerabilities

- **Signature replay**: Same signature valid across chains (no chainId), across contracts
- **Signature malleability**: `ecrecover` accepts malleable signatures (flip s value)
- **Missing nonce**: Same signature used twice → double-spend
- **`ecrecover` returns 0**: When signature is invalid, returns `address(0)` — if not checked, `address(0)` may have special privileges

## Exploit development template (Foundry)

```solidity
// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;
import "forge-std/Script.sol";
import "forge-std/console.sol";

contract Exploit is Script {
    function run() external {
        vm.startBroadcast();
        // Target contract
        Challenge challenge = Challenge(<address>);
        // Exploit logic here
        // ...
        vm.stopBroadcast();
        // Verify: solved?
        console.log("Solved:", challenge.isSolved());
    }
}
```

```bash
forge script script/Exploit.sol --rpc-url <rpc> --broadcast -vvvv
```

## Evidence rules

- Save the exploit contract to `/mnt/project/exploit/solve.sol` (or the Foundry/Hardhat project).
- Save the transaction hash and block explorer link as evidence.
- Document: vulnerability type, affected contract(s), function(s), exploit path, and verification (isSolved() or flag).
- For CTF, submit the flag/hash as required by the platform.

## Prefix examples

```text
[cypher:finding type=VULN_CANDIDATE confidence=0.88 severity=high tags=ctf,blockchain,reentrancy artifacts=/mnt/project/vuln-research/reentrancy-analysis.md cleanup=none] `withdraw()` in `Vault.sol` sends ETH before updating `balances` — classic reentrancy. No `nonReentrant` modifier. External call at line 42.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=critical tags=ctf,blockchain,reentrancy artifacts=/mnt/project/exploit/solve.sol cleanup=none] Reentrancy exploit drains Vault for 10 ETH. isSolved() returns true. Tx: 0x...
```

## Common CTF blockchain patterns

- Missing `nonReentrant` modifier on external-call functions
- `tx.origin` check (phishable)
- Unchecked low-level calls: `bool success` not checked
- `delegatecall` with user-controlled address
- ERC721/ERC1155 reentrancy (onERC721Received callback)
- `block.timestamp` used for randomness or critical logic
- `selfdestruct` can force-send ETH to a contract that assumes `address(this).balance` only increases via its own logic
- `abi.encodePacked` with dynamic types (hash collision)
- Assembly block with `delegatecall` / `call` to user-supplied address
- Uninitialized implementation contract (UUPS proxy pattern)
