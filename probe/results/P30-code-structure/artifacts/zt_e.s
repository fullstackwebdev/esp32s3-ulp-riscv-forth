	.file	"zt.c"
	.option nopic
	.attribute arch, "rv32i2p1_m2p0_c2p0_zicsr2p0_zifencei2p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.type	wz.constprop.0, @function
wz.constprop.0:
	addi	a5,a0,140
.L2:
	sw	zero,0(a0)
	addi	a0,a0,4
	bne	a0,a5,.L2
	ret
	.size	wz.constprop.0, .-wz.constprop.0
	.align	1
	.globl	zero_a
	.type	zero_a, @function
zero_a:
	li	a5,144
	mul	a0,a0,a5
	lui	a5,%hi(tsk)
	addi	a5,a5,%lo(tsk)
	li	a4,16
	add	a0,a0,a5
	li	a5,0
.L5:
	sw	zero,0(a0)
	sw	zero,64(a0)
	addi	a5,a5,1
	addi	a0,a0,4
	bne	a5,a4,.L5
	ret
	.size	zero_a, .-zero_a
	.align	1
	.globl	zero_b
	.type	zero_b, @function
zero_b:
	li	a5,144
	mul	a0,a0,a5
	lui	a5,%hi(tsk)
	addi	a5,a5,%lo(tsk)
	add	a0,a5,a0
	tail	wz.constprop.0
	.size	zero_b, .-zero_b
	.align	1
	.globl	zero_c
	.type	zero_c, @function
zero_c:
	li	a5,144
	mul	a0,a0,a5
	lui	a5,%hi(tsk)
	addi	a5,a5,%lo(tsk)
	add	a0,a0,a5
	addi	a5,a0,144
.L9:
	sw	zero,12(a0)
	sw	zero,8(a0)
	sw	zero,4(a0)
	sw	zero,0(a0)
	addi	a0,a0,16
	bne	a0,a5,.L9
	ret
	.size	zero_c, .-zero_c
	.ident	"GCC: (crosstool-NG esp-14.2.0_20241119) 14.2.0"
	.section	.note.GNU-stack,"",@progbits
