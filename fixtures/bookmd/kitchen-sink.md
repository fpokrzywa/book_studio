# The Kitchen Sink {#kitchen}

A paragraph with *emphasis*, **strong text**, ~~struck text~~, `inline code`, a [link](https://example.com "Example"),
inline math $E = mc^2$, a citation [@smith2020, p. 12], two citations [@doe2019; -@roe2021], and a footnote.[^note]

## Lists {#lists}

- First item
- Second item with *emphasis*
  - Nested item

1. One
2. Two

- [ ] Task to do
- [x] Task done

> A block quote with **strong** text.
>
> Second quote paragraph.

## Table {#tables}

| Part | Torque | Notes |
|:-----|-------:|:-----:|
| Bolt | 12 Nm  | dry   |
| Nut  | 8 Nm   | a \| b |

: Fastener torque values {#tbl-torque}

## Code and math {#code}

```python {#lst-start}
def start(engine):
	return engine.ignite()  # tab and trailing spaces kept  
```

$$
\int_0^1 x^2 \, dx = \frac{1}{3}
$$ (eq-area)

## Figure {#figures}

![The engine at rest, seen from the left](asset:0123456789abcdef){#fig-engine alt="Line drawing of a small two-stroke engine" width="60%"}

::: {.callout-note #note-safety}
Always disconnect the spark plug before working on the engine.
:::

***

[^note]: The footnote text, with *emphasis*.
