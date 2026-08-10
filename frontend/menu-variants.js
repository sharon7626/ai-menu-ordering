(function exposeMenuVariants(globalObject) {
  function parseVariantName(itemName) {
    const match = String(itemName ?? "").trim().match(/^(.*?)[（(]\s*([^（）()]+?)\s*[）)]$/u);
    if (!match || !match[1].trim() || !match[2].trim()) {
      return null;
    }
    const rawVariantName = match[2].trim();
    const variantName = /^(M|L|XL)$/i.test(rawVariantName)
      ? rawVariantName.toUpperCase()
      : rawVariantName;
    return {
      baseName: match[1].trim(),
      variantName,
    };
  }

  function groupItems(items, getName = (item) => item.name) {
    const parsedItems = items.map((item) => ({
      item,
      variant: parseVariantName(getName(item)),
    }));
    const variantsByBaseName = new Map();

    parsedItems.forEach((entry) => {
      if (!entry.variant) return;
      const groupKey = entry.variant.baseName.toLocaleLowerCase("zh-TW");
      if (!variantsByBaseName.has(groupKey)) variantsByBaseName.set(groupKey, []);
      variantsByBaseName.get(groupKey).push(entry);
    });

    const renderedItems = new Set();
    const groups = [];
    parsedItems.forEach((entry) => {
      if (renderedItems.has(entry.item)) return;
      const groupKey = entry.variant?.baseName.toLocaleLowerCase("zh-TW");
      const variants = groupKey ? variantsByBaseName.get(groupKey) : null;
      if (variants && variants.length > 1) {
        variants.forEach((member) => renderedItems.add(member.item));
        groups.push({
          type: "variants",
          baseName: entry.variant.baseName,
          variants,
        });
      } else {
        renderedItems.add(entry.item);
        groups.push({ type: "item", item: entry.item });
      }
    });
    return groups;
  }

  const api = { parseVariantName, groupItems };
  globalObject.MenuVariants = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
}(typeof window !== "undefined" ? window : globalThis));
