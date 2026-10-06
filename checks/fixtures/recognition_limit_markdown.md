根据图片内容，这里只有一道题目，整理及解答如下：

**题目：**
计算极限 $\lim_{x \to a+0} \frac{\sqrt{x} - \sqrt{a} + \sqrt{x-a}}{\sqrt{x^2 - a^2}} \quad (a \ge 0)$

**解答：**

为了计算该极限，我们需要对分子和分母分别进行分析。首先，由于 $x \to a+0$，我们有 $x > a$，因此 $x-a > 0$，表达式中的根式在实数范围内均有意义。同时，分母 $\sqrt{x^2 - a^2} = \sqrt{(x-a)(x+a)}$。当 $x \to a+0$ 时，分母趋于 $0$。

我们需要分情况讨论 $a$ 的取值：

**情况 1：当 $a > 0$ 时**

当 $x \to a+0$ 时，$\sqrt{x} - \sqrt{a} \to 0$ 且 $\sqrt{x-a} \to 0$，分子分母均趋于 $0$，属于 $\frac{0}{0}$ 型未定式。

为了消去分母中的根号，我们可以将分子进行有理化。考虑到分子包含两项，我们可以乘以共轭表达式：
$$
\begin{aligned}
\lim_{x \to a+0} \frac{\sqrt{x} - \sqrt{a} + \sqrt{x-a}}{\sqrt{x^2 - a^2}} &= \lim_{x \to a+0} \frac{(\sqrt{x} - \sqrt{a}) + \sqrt{x-a}}{\sqrt{(x-a)(x+a)}} \\
&= \lim_{x \to a+0} \frac{(\sqrt{x} - \sqrt{a}) + \sqrt{x-a}}{\sqrt{x-a}\sqrt{x+a}}
\end{aligned}
$$
将上述表达式拆分为两项：
$$
= \lim_{x \to a+0} \left( \frac{\sqrt{x} - \sqrt{a}}{\sqrt{x-a}\sqrt{x+a}} + \frac{\sqrt{x-a}}{\sqrt{x-a}\sqrt{x+a}} \right)
$$
对于第一项，分子分母同时乘以 $(\sqrt{x} + \sqrt{a})$ 进行有理化：
$$
\frac{\sqrt{x} - \sqrt{a}}{\sqrt{x-a}\sqrt{x+a}} = \frac{x - a}{(\sqrt{x} + \sqrt{a})\sqrt{x-a}\sqrt{x+a}} = \frac{(\sqrt{x-a})^2}{(\sqrt{x} + \sqrt{a})\sqrt{x-a}\sqrt{x+a}} = \frac{\sqrt{x-a}}{(\sqrt{x} + \sqrt{a})\sqrt{x+a}}
$$
将其代回极限表达式中：
$$
\begin{aligned}
&= \lim_{x \to a+0} \left( \frac{\sqrt{x-a}}{(\sqrt{x} + \sqrt{a})\sqrt{x+a}} + \frac{1}{\sqrt{x+a}} \right) \\
&= \lim_{x \to a+0} \frac{\sqrt{x-a}}{(\sqrt{x} + \sqrt{a})\sqrt{x+a}} + \lim_{x \to a+0} \frac{1}{\sqrt{x+a}}
\end{aligned}
$$
由于当 $x \to a+0$ 时，$x-a \to 0$，第一项的极限为：
$$
\frac{0}{(\sqrt{a} + \sqrt{a})\sqrt{2a}} = 0
$$
第二项的极限为：
$$
\frac{1}{\sqrt{2a}}
$$
因此，当 $a > 0$ 时，原极限为 $\frac{1}{\sqrt{2a}}$。

**情况 2：当 $a = 0$ 时**

原极限变为：
$$
\lim_{x \to 0+} \frac{\sqrt{x} - 0 + \sqrt{x}}{\sqrt{x^2}} = \lim_{x \to 0+} \frac{2\sqrt{x}}{x} = \lim_{x \to 0+} \frac{2}{\sqrt{x}}
$$
由于当 $x \to 0+$ 时，$\frac{2}{\sqrt{x}} \to +\infty$，所以该极限不存在（趋于正无穷）。

**综上所述：**
$$
\lim_{x \to a+0} \frac{\sqrt{x} - \sqrt{a} + \sqrt{x-a}}{\sqrt{x^2 - a^2}} =
\begin{cases}
\frac{1}{\sqrt{2a}}, & a > 0 \\
+\infty, & a = 0
\end{cases}
$$
