document.addEventListener("DOMContentLoaded", function() {
    var blockquotes = document.querySelectorAll('blockquote');

    blockquotes.forEach(function(blockquote) {
        // Get all child nodes of the blockquote
        var childNodes = Array.from(blockquote.childNodes);

        // Prepare a container for text content
        var textContent = '';

        // Extract text content from all child nodes except <cite>
        childNodes.forEach(function(node) {
            if (node.nodeType === Node.TEXT_NODE || (node.nodeType === Node.ELEMENT_NODE && node.tagName.toLowerCase() !== 'cite')) {
                textContent += node.textContent;
            }
        });

        // Find the previous sibling that is not a text node (like a <p> or other element)
        var previousElement = blockquote.previousElementSibling;

        // If the previous sibling exists and is not a <cite> or blockquote
        if (previousElement && previousElement.tagName.toLowerCase() !== 'cite') {
            // Append the extracted text content to the previous sibling's text
            previousElement.textContent += " " + textContent.trim();
        } else {
            // If there isn't a suitable previous sibling, just insert the text before the blockquote
            var textNode = document.createTextNode(textContent.trim());
            blockquote.parentNode.insertBefore(textNode, blockquote);
        }

        // Finally, remove the blockquote element
        blockquote.remove();
    });
});




document.addEventListener("DOMContentLoaded", function() {
    // Select all <dl.simple> elements
    let dlElements = document.querySelectorAll('dl.simple');

    // Filter out <dl.simple> elements that are inside a <dl class="field-list simple">
    dlElements = Array.from(dlElements).filter(dl => {
        return !dl.closest('dl.field-list.simple');
    });

    dlElements.forEach(function(dlElement) {
        // Check if the <dl> contains any <span class="classifier">
        var hasClassifier = dlElement.querySelector('span.classifier');

        // If there's no <span class="classifier">, proceed with the replacement
        if (!hasClassifier) {
            // Create a new <p> element
            var newP = document.createElement('p');

            // Extract all text content from the <dl> element and its children
            var textContent = Array.from(dlElement.childNodes)
                .map(node => node.textContent.trim())
                .filter(text => text.length > 0)  // Remove any empty strings
                .join(' ');  // Combine all text with a space

            newP.textContent = textContent;

            // Replace the <dl> element with the new <p> element
            dlElement.parentNode.replaceChild(newP, dlElement);
        }
    });
});


document.addEventListener("DOMContentLoaded", function() {
    // Function to add an icon before the link text
    function addIconBasedOnText(linkText, iconClass) {
        var links = document.querySelectorAll('li.toctree-l1 > a'); // Select all level-1 toctree links
        links.forEach(function(link) {
            if (link.textContent.trim() === linkText) { // Check if the link text matches
                var icon = document.createElement('i');
                icon.className = 'fa-solid ' + iconClass;
                icon.style.marginRight = '5px';
                icon.style.width = '1.5em';
                icon.style.display = 'inline-block';
                icon.style.textAlign = 'center';
                icon.style.verticalAlign = 'middle';

                // Insert the icon before the link text
                link.prepend(icon);
            }
        });
    }

    // Add icons based on the link text
    addIconBasedOnText('Quickstart Guide', 'fa-compass');
    addIconBasedOnText('API Reference', 'fa-book');
});
