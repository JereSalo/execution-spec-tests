"""
abstract: Tests `BLOBHASH` opcode in [EIP-4844: Shard Blob Transactions](https://eips.ethereum.org/EIPS/eip-4844)
    Test cases for the `BLOBHASH` opcode in
    [EIP-4844: Shard Blob Transactions](https://eips.ethereum.org/EIPS/eip-4844).

note: Adding a new test
    Add a function that is named `test_<test_name>` and takes at least the following arguments:

    - blockchain_test
    - pre
    - tx
    - post

    Additional custom `pytest.fixture` fixtures can be added and parametrized for new test cases.

    There is no specific structure to follow within this test module.

"""  # noqa: E501

from typing import List

import pytest

from ethereum_test_forks import Fork
from ethereum_test_tools import (
    Account,
    Address,
    Alloc,
    AuthorizationTuple,
    Block,
    BlockchainTestFiller,
    CodeGasMeasure,
    Environment,
    Hash,
    StateTestFiller,
    Transaction,
    add_kzg_version,
)
from ethereum_test_tools import Opcodes as Op

from .spec import Spec, ref_spec_4844

REFERENCE_SPEC_GIT_PATH = ref_spec_4844.git_path
REFERENCE_SPEC_VERSION = ref_spec_4844.version

pytestmark = pytest.mark.valid_from("Cancun")


# Blobhash index values for test_blobhash_gas_cost
blobhash_index_values = [
    0x00,
    0x01,
    0x02,
    0x03,
    0x04,
    2**256 - 1,
    0xA12C8B6A8B11410C7D98D790E1098F1ED6D93CB7A64711481AAAB1848E13212F,
]

# Random fixed list of blob versioned hashes
random_blob_hashes = add_kzg_version(
    [
        "0x00b8c5b09810b5fc07355d3da42e2c3a3e200c1d9a678491b7e8e256fc50cc4f",
        "0x005b4c8cc4f86aa2d2cf9e9ce97fca704a11a6c20f6b1d6c00a6e15f6d60a6df",
        "0x00878f80eaf10be1a6f618e6f8c071b10a6c14d9b89a3bf2a3f3cf2db6c5681d",
        "0x004eb72b108d562c639faeb6f8c6f366a28b0381c7d30431117ec8c7bb89f834",
        "0x00a9b2a6c3f3f0675b768d49b5f5dc5b5d988f88d55766247ba9e40b125f16bb",
        "0x00a4d4cde4aa01e57fb2c880d1d9c778c33bdf85e48ef4c4d4b4de51abccf4ed",
        "0x0071c9b8a0c72d38f5e5b5d08e5cb5ce5e23fb1bc5d75f9c29f7b94df0bceeb7",
        "0x002c8b6a8b11410c7d98d790e1098f1ed6d93cb7a64711481aaab1848e13212f",
        "0x00d78c25f8a1d6aa04d0e2e2a71cf8dfaa4239fa0f301eb57c249d1e6bfe3c3d",
        "0x00c778eb1348a73b9c30c7b1d282a5f8b2c5b5a12d5c5e4a4a35f9c5f639b4a4",
    ],
    Spec.BLOB_COMMITMENT_VERSION_KZG,
)


class BlobhashScenario:
    """A utility class for generating blobhash calls."""

    @staticmethod
    def create_blob_hashes_list(length: int, max_blobs_per_block: int) -> List[List[Hash]]:
        """
        Create list of MAX_BLOBS_PER_BLOCK blob hashes
        using `random_blob_hashes`.

        Cycle over random_blob_hashes to get a large list of
        length: MAX_BLOBS_PER_BLOCK * length
        -> [0x01, 0x02, 0x03, 0x04, ..., 0x0A, 0x0B, 0x0C, 0x0D]

        Then split list into smaller chunks of max_blobs_per_block
        -> [[0x01, 0x02, 0x03, 0x04], ..., [0x0a, 0x0b, 0x0c, 0x0d]]
        """
        b_hashes = [
            random_blob_hashes[i % len(random_blob_hashes)]
            for i in range(max_blobs_per_block * length)
        ]
        return [
            b_hashes[i : i + max_blobs_per_block]
            for i in range(0, len(b_hashes), max_blobs_per_block)
        ]

    @staticmethod
    def blobhash_sstore(index: int, max_blobs_per_block: int):
        """
        Return BLOBHASH sstore to the given index.

        If the index is out of the valid bounds, 0x01 is written
        in storage, as we later check it is overwritten by
        the BLOBHASH sstore.
        """
        invalidity_check = Op.SSTORE(index, 0x01)
        if index < 0 or index >= max_blobs_per_block:
            return invalidity_check + Op.SSTORE(index, Op.BLOBHASH(index))
        return Op.SSTORE(index, Op.BLOBHASH(index))

    @classmethod
    def generate_blobhash_bytecode(cls, scenario_name: str, max_blobs_per_block: int) -> bytes:
        """Return BLOBHASH bytecode for the given scenario."""
        scenarios = {
            "single_valid": sum(
                cls.blobhash_sstore(i, max_blobs_per_block) for i in range(max_blobs_per_block)
            ),
            "repeated_valid": sum(
                sum(cls.blobhash_sstore(i, max_blobs_per_block) for _ in range(10))
                for i in range(max_blobs_per_block)
            ),
            "valid_invalid": sum(
                cls.blobhash_sstore(i, max_blobs_per_block)
                + cls.blobhash_sstore(max_blobs_per_block, max_blobs_per_block)
                + cls.blobhash_sstore(i, max_blobs_per_block)
                for i in range(max_blobs_per_block)
            ),
            "varied_valid": sum(
                cls.blobhash_sstore(i, max_blobs_per_block)
                + cls.blobhash_sstore(i + 1, max_blobs_per_block)
                + cls.blobhash_sstore(i, max_blobs_per_block)
                for i in range(max_blobs_per_block - 1)
            ),
            "invalid_calls": sum(
                cls.blobhash_sstore(i, max_blobs_per_block)
                for i in range(-5, max_blobs_per_block + 5)
            ),
        }
        scenario = scenarios.get(scenario_name)
        if scenario is None:
            raise ValueError(f"Invalid scenario: {scenario_name}")
        return scenario


@pytest.mark.parametrize("blobhash_index", blobhash_index_values)
@pytest.mark.with_all_tx_types
def test_blobhash_gas_cost(
    pre: Alloc,
    fork: Fork,
    tx_type: int,
    blobhash_index: int,
    state_test: StateTestFiller,
    target_blobs_per_block: int,
):
    """
    Tests `BLOBHASH` opcode gas cost using a variety of indexes.

    Asserts that the gas consumption of the `BLOBHASH` opcode is correct by ensuring
    it matches `HASH_OPCODE_GAS = 3`. Includes both valid and invalid random
    index sizes from the range `[0, 2**256-1]`, for tx types 2 and 3.
    """
    gas_measure_code = CodeGasMeasure(
        code=Op.BLOBHASH(blobhash_index),
        overhead_cost=3,
        extra_stack_items=1,
    )

    address = pre.deploy_contract(gas_measure_code)
    sender = pre.fund_eoa()

    tx_kwargs = {
        "ty": tx_type,
        "sender": sender,
        "to": address,
        "data": Hash(0),
        "gas_limit": 500_000,
        "max_fee_per_blob_gas": (fork.min_base_fee_per_blob_gas() * 10) if tx_type == 3 else None,
        "blob_versioned_hashes": random_blob_hashes[0:target_blobs_per_block]
        if tx_type == 3
        else None,
    }
    if tx_type == 4:
        signer = pre.fund_eoa(amount=0)
        tx_kwargs["authorization_list"] = [
            AuthorizationTuple(
                signer=signer,
                address=Address(0),
                nonce=0,
            )
        ]

    tx = Transaction(**tx_kwargs)
    post = {address: Account(storage={0: Spec.HASH_GAS_COST})}

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post=post,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "single_valid",
        "repeated_valid",
        "valid_invalid",
        "varied_valid",
    ],
)
def test_blobhash_scenarios(
    pre: Alloc,
    fork: Fork,
    scenario: str,
    blockchain_test: BlockchainTestFiller,
    max_blobs_per_block: int,
):
    """
    Tests that the `BLOBHASH` opcode returns the correct versioned hash for
    various valid indexes.

    Covers various scenarios with random `blob_versioned_hash` values within
    the valid range `[0, 2**256-1]`.
    """
    total_blocks = 5
    b_hashes_list = BlobhashScenario.create_blob_hashes_list(
        length=total_blocks, max_blobs_per_block=max_blobs_per_block
    )
    blobhash_calls = BlobhashScenario.generate_blobhash_bytecode(
        scenario_name=scenario, max_blobs_per_block=max_blobs_per_block
    )
    sender = pre.fund_eoa()

    blocks: List[Block] = []
    post = {}
    for i in range(total_blocks):
        address = pre.deploy_contract(blobhash_calls)
        blocks.append(
            Block(
                txs=[
                    Transaction(
                        ty=Spec.BLOB_TX_TYPE,
                        sender=sender,
                        to=address,
                        data=Hash(0),
                        gas_limit=500_000,
                        access_list=[],
                        max_fee_per_blob_gas=(fork.min_base_fee_per_blob_gas() * 10),
                        blob_versioned_hashes=b_hashes_list[i],
                    )
                ]
            )
        )
        post[address] = Account(
            storage={index: b_hashes_list[i][index] for index in range(max_blobs_per_block)}
        )
    blockchain_test(
        pre=pre,
        blocks=blocks,
        post=post,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "invalid_calls",
    ],
)
def test_blobhash_invalid_blob_index(
    pre: Alloc,
    fork: Fork,
    blockchain_test: BlockchainTestFiller,
    scenario: str,
    max_blobs_per_block: int,
):
    """
    Tests that the `BLOBHASH` opcode returns a zeroed `bytes32` value for invalid
    indexes.

    Includes cases where the index is negative (`index < 0`) or
    exceeds the maximum number of `blob_versioned_hash` values stored:
    (`index >= len(tx.message.blob_versioned_hashes)`).

    It confirms that the returned value is a zeroed `bytes32` for each case.
    """
    total_blocks = 5
    blobhash_calls = BlobhashScenario.generate_blobhash_bytecode(
        scenario_name=scenario, max_blobs_per_block=max_blobs_per_block
    )
    sender = pre.fund_eoa()
    blocks: List[Block] = []
    post = {}
    for i in range(total_blocks):
        address = pre.deploy_contract(blobhash_calls)
        blob_per_block = (i % max_blobs_per_block) + 1
        blobs = [random_blob_hashes[blob] for blob in range(blob_per_block)]
        blocks.append(
            Block(
                txs=[
                    Transaction(
                        ty=Spec.BLOB_TX_TYPE,
                        sender=sender,
                        to=address,
                        gas_limit=500_000,
                        data=Hash(0),
                        access_list=[],
                        max_fee_per_blob_gas=(fork.min_base_fee_per_blob_gas() * 10),
                        blob_versioned_hashes=blobs,
                    )
                ]
            )
        )
        post[address] = Account(
            storage={
                index: (0 if index < 0 or index >= blob_per_block else blobs[index])
                for index in range(
                    -total_blocks,
                    blob_per_block + (total_blocks - (i % max_blobs_per_block)),
                )
            }
        )
    blockchain_test(
        pre=pre,
        blocks=blocks,
        post=post,
    )


def test_blobhash_multiple_txs_in_block(
    pre: Alloc,
    fork: Fork,
    blockchain_test: BlockchainTestFiller,
    max_blobs_per_block: int,
):
    """
    Tests that the `BLOBHASH` opcode returns the appropriate values when there
    is more than 1 blob tx type within a block (for tx types 2 and 3).

    Scenarios involve tx type 3 followed by tx type 2 running the same code
    within a block, including the opposite.
    """
    blobhash_bytecode = BlobhashScenario.generate_blobhash_bytecode(
        scenario_name="single_valid", max_blobs_per_block=max_blobs_per_block
    )
    addresses = [pre.deploy_contract(blobhash_bytecode) for _ in range(4)]
    sender = pre.fund_eoa()

    def blob_tx(address: Address, tx_type: int):
        return Transaction(
            ty=tx_type,
            sender=sender,
            to=address,
            data=Hash(0),
            gas_limit=500_000,
            access_list=[] if tx_type >= 1 else None,
            max_fee_per_blob_gas=(fork.min_base_fee_per_blob_gas() * 10) if tx_type >= 3 else None,
            blob_versioned_hashes=random_blob_hashes[0:max_blobs_per_block]
            if tx_type >= 3
            else None,
        )

    blocks = [
        Block(
            txs=[
                blob_tx(address=addresses[0], tx_type=3),
                blob_tx(address=addresses[0], tx_type=2),
            ]
        ),
        Block(
            txs=[
                blob_tx(address=addresses[1], tx_type=2),
                blob_tx(address=addresses[1], tx_type=3),
            ]
        ),
        Block(
            txs=[
                blob_tx(address=addresses[2], tx_type=2),
                blob_tx(address=addresses[3], tx_type=3),
            ],
        ),
    ]
    post = {
        Address(address): Account(
            storage={i: random_blob_hashes[i] for i in range(max_blobs_per_block)}
        )
        if address in (addresses[1], addresses[3])
        else Account(storage={i: 0 for i in range(max_blobs_per_block)})
        for address in addresses
    }
    blockchain_test(
        pre=pre,
        blocks=blocks,
        post=post,
    )
