/* Link map for bench.c on the C5517: 64 KB DARAM, 256 KB SARAM (addresses in bytes).
   SPDX-License-Identifier: MIT */
MEMORY
{
    MMR:   o = 0x000000  l = 0x0000C0
    DARAM: o = 0x0000C0  l = 0x00FF40   /* 64 KB dual-access */
    SARAM: o = 0x010000  l = 0x040000   /* 256 KB single-access */
    VECS:  o = 0xFFFF00  l = 0x000100
}
SECTIONS
{
    vectors (NOLOAD) > VECS
    .stack    > DARAM, RUN_START(_stk_start), RUN_END(_stk_end)
    .sysstack > DARAM, RUN_START(_sstk_start), RUN_END(_sstk_end)
    .sysmem   > DARAM (HIGH)   /* the heap: encoder and decoder states */
    .cio      > DARAM
    .data     > DARAM
    .bss      > SARAM     /* the benchmark's own buffers */
    .cinit    > SARAM
    .const    > SARAM
    .switch   > SARAM
    .text     > SARAM
}
